import json
import os
import asyncpg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://lawemu:changeme_in_production@localhost:5432/lawemu",
)

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=20,
            command_timeout=60,
        )
    return _pool


async def get_pool() -> asyncpg.Pool:
    return await _get_pool()


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ── Init ─────────────────────────────────────────────────

async def init_db():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                role TEXT NOT NULL DEFAULT 'user',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                case_type TEXT NOT NULL,
                court_name TEXT DEFAULT '',
                our_role TEXT NOT NULL,
                case_facts TEXT NOT NULL,
                our_claims TEXT DEFAULT '',
                our_evidence TEXT DEFAULT '',
                our_legal_basis TEXT DEFAULT '',
                opposing_claims TEXT DEFAULT '',
                opposing_evidence TEXT DEFAULT '',
                opposing_legal_basis TEXT DEFAULT '',
                judge_tendencies TEXT DEFAULT '',
                additional_context TEXT DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_sessions (
                id TEXT PRIMARY KEY,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                mode TEXT NOT NULL,
                messages JSONB NOT NULL DEFAULT '[]',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS backup_schedule (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                enabled BOOLEAN DEFAULT true,
                cron_hour INTEGER DEFAULT 2,
                cron_minute INTEGER DEFAULT 0,
                keep_count INTEGER DEFAULT 7,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            INSERT INTO backup_schedule (id) VALUES (1) ON CONFLICT DO NOTHING
        """)
        # Migrate: add user_id to cases if missing
        col_exists = await conn.fetchval("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'cases' AND column_name = 'user_id'
        """)
        if not col_exists:
            await conn.execute("ALTER TABLE cases ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
            # assign orphan cases to first admin (or user id 1)
            first_user = await conn.fetchval("SELECT id FROM users ORDER BY id LIMIT 1")
            if first_user:
                await conn.execute("UPDATE cases SET user_id = $1 WHERE user_id IS NULL", first_user)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS case_records (
                id SERIAL PRIMARY KEY,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                record_type TEXT NOT NULL DEFAULT 'hearing',
                content_text TEXT NOT NULL DEFAULT '',
                file_name TEXT DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id SERIAL PRIMARY KEY,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                focus TEXT NOT NULL,
                analysis_text TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS generated_documents (
                id SERIAL PRIMARY KEY,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                doc_type TEXT NOT NULL,
                doc_title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_config (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                provider TEXT NOT NULL DEFAULT 'ollama',
                base_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                context_window INTEGER DEFAULT 20000,
                timeout INTEGER DEFAULT 3600,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            INSERT INTO llm_config (id) VALUES (1) ON CONFLICT DO NOTHING
        """)

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_user_id ON cases(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_case_id ON simulation_sessions(case_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_records_case_id ON case_records(case_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_history_case_id ON analysis_history(case_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_generated_docs_case_id ON generated_documents(case_id)")

        # Seed default admin if no users exist
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        if user_count == 0:
            import bcrypt
            pw = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode("utf-8")
            await conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role) VALUES ($1, $2, $3, $4)",
                "admin", pw, "管理员", "admin",
            )


# ── User CRUD ────────────────────────────────────────────

async def create_user(username: str, password_hash: str, display_name: str = "", role: str = "user") -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO users (username, password_hash, display_name, role)
               VALUES ($1, $2, $3, $4) RETURNING *""",
            username, password_hash, display_name, role,
        )
        return _user_to_dict(row)


async def get_user_by_username(username: str) -> dict | None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
        return _user_to_dict(row) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return _user_to_dict(row) if row else None


async def list_users() -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users ORDER BY created_at")
        return [_user_to_dict(r) for r in rows]


async def update_user(user_id: int, **fields) -> dict | None:
    pool = await _get_pool()
    sets = []
    vals = []
    idx = 1
    for k, v in fields.items():
        if v is not None:
            sets.append(f"{k} = ${idx}")
            vals.append(v)
            idx += 1
    if not sets:
        return await get_user_by_id(user_id)
    vals.append(user_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE users SET {', '.join(sets)} WHERE id = ${idx} RETURNING *", *vals
        )
        return _user_to_dict(row) if row else None


async def delete_user(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        return result.split()[-1] != "0"


async def count_users() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users")


def _user_to_dict(row) -> dict:
    d = dict(row)
    d.pop("password_hash", None)
    return d


# ── Case CRUD ────────────────────────────────────────────

async def save_case(case_data: dict) -> int:
    pool = await _get_pool()
    cols = list(case_data.keys())
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    col_names = ", ".join(cols)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"INSERT INTO cases ({col_names}) VALUES ({placeholders}) RETURNING id",
            *case_data.values(),
        )
        return row["id"]


async def get_case(case_id: int) -> dict | None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM cases WHERE id = $1", case_id)
        return dict(row) if row else None


async def list_cases(user_id: int | None = None) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if user_id is not None:
            rows = await conn.fetch(
                "SELECT * FROM cases WHERE user_id = $1 ORDER BY created_at DESC", user_id
            )
            return [dict(r) for r in rows]
        else:
            rows = await conn.fetch(
                """SELECT c.*, u.username AS owner_name, u.display_name AS owner_display_name
                   FROM cases c LEFT JOIN users u ON c.user_id = u.id
                   ORDER BY c.created_at DESC"""
            )
            return [dict(r) for r in rows]


async def update_case(case_id: int, **fields) -> dict | None:
    pool = await _get_pool()
    sets = []
    vals = []
    idx = 1
    for k, v in fields.items():
        if v is not None:
            sets.append(f"{k} = ${idx}")
            vals.append(v)
            idx += 1
    if not sets:
        return await get_case(case_id)
    vals.append(case_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE cases SET {', '.join(sets)} WHERE id = ${idx} RETURNING *", *vals
        )
        return dict(row) if row else None


async def delete_case(case_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM cases WHERE id = $1", case_id)
        return result.split()[-1] != "0"


# ── Session CRUD ─────────────────────────────────────────

async def save_session(session_id: str, case_id: int, mode: str, messages: list):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO simulation_sessions (id, case_id, mode, messages, created_at)
               VALUES ($1, $2, $3, $4::jsonb, NOW())
               ON CONFLICT (id) DO UPDATE
               SET messages = $4::jsonb, created_at = NOW()""",
            session_id, case_id, mode, json.dumps(messages, ensure_ascii=False),
        )


async def get_session(session_id: str) -> dict | None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM simulation_sessions WHERE id = $1", session_id
        )
        if row:
            result = dict(row)
            if isinstance(result["messages"], str):
                result["messages"] = json.loads(result["messages"])
            return result
        return None


# ── Backup Schedule ──────────────────────────────────────

async def get_backup_schedule() -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM backup_schedule WHERE id = 1")
        return dict(row) if row else {"enabled": True, "cron_hour": 2, "cron_minute": 0, "keep_count": 7}


async def update_backup_schedule(enabled: bool, cron_hour: int, cron_minute: int, keep_count: int) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE backup_schedule
               SET enabled=$1, cron_hour=$2, cron_minute=$3, keep_count=$4, updated_at=NOW()
               WHERE id=1 RETURNING *""",
            enabled, cron_hour, cron_minute, keep_count,
        )
        return dict(row)


# ── Admin Statistics ─────────────────────────────────────

async def get_admin_statistics() -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_cases = await conn.fetchval("SELECT COUNT(*) FROM cases")
        total_sessions = await conn.fetchval("SELECT COUNT(*) FROM simulation_sessions")

        by_user = await conn.fetch("""
            SELECT u.id, u.username, u.display_name, u.role,
                   COUNT(DISTINCT c.id) AS case_count,
                   COUNT(DISTINCT s.id) AS session_count
            FROM users u
            LEFT JOIN cases c ON c.user_id = u.id
            LEFT JOIN simulation_sessions s ON s.case_id = c.id
            GROUP BY u.id, u.username, u.display_name, u.role
            ORDER BY case_count DESC
        """)

        by_type = await conn.fetch("""
            SELECT case_type, COUNT(*) AS count
            FROM cases GROUP BY case_type ORDER BY count DESC
        """)

        recent_cases = await conn.fetch("""
            SELECT c.title, c.case_type, c.created_at,
                   u.display_name AS owner
            FROM cases c LEFT JOIN users u ON c.user_id = u.id
            ORDER BY c.created_at DESC LIMIT 10
        """)

        return {
            "total_users": total_users,
            "total_cases": total_cases,
            "total_sessions": total_sessions,
            "by_user": [dict(r) for r in by_user],
            "by_case_type": [dict(r) for r in by_type],
            "recent_cases": [dict(r) for r in recent_cases],
        }


# ── Monitoring Queries ───────────────────────────────────

async def get_db_health() -> dict:
    """Quick health check: verify DB is reachable and responsive."""
    try:
        pool = await _get_pool()
        async with pool.acquire(timeout=5) as conn:
            ver = await conn.fetchval("SELECT version()")
            uptime = await conn.fetchval(
                "SELECT now() - pg_postmaster_start_time()"
            )
            is_in_recovery = await conn.fetchval("SELECT pg_is_in_recovery()")
            db_name = await conn.fetchval("SELECT current_database()")
            return {
                "status": "healthy",
                "message": "数据库运行正常",
                "version": ver,
                "database": db_name,
                "uptime": str(uptime).split(".")[0] if uptime else "",
                "is_replica": is_in_recovery,
                "pool_size": pool.get_size(),
                "pool_free": pool.get_idle_size(),
                "pool_min": pool.get_min_size(),
                "pool_max": pool.get_max_size(),
            }
    except asyncpg.InvalidCatalogNameError as e:
        return {"status": "error", "message": f"数据库不存在: {e}"}
    except asyncpg.InvalidPasswordError as e:
        return {"status": "error", "message": f"认证失败: {e}"}
    except OSError as e:
        return {"status": "error", "message": f"无法连接到数据库服务器: {e}"}
    except asyncpg.PostgresError as e:
        return {"status": "error", "message": f"数据库错误: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"连接失败: {type(e).__name__}: {e}"}


async def get_db_stats() -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        db_size = await conn.fetchval("SELECT pg_size_pretty(pg_database_size(current_database()))")
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        case_count = await conn.fetchval("SELECT COUNT(*) FROM cases")
        session_count = await conn.fetchval("SELECT COUNT(*) FROM simulation_sessions")
        tables = await conn.fetch("""
            SELECT relname AS name,
                   n_live_tup AS row_count,
                   pg_size_pretty(pg_total_relation_size(relid)) AS size
            FROM pg_stat_user_tables ORDER BY n_live_tup DESC
        """)
        active_conns = await conn.fetchval(
            "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()"
        )
        return {
            "database_size": db_size,
            "user_count": user_count,
            "case_count": case_count,
            "session_count": session_count,
            "active_connections": active_conns,
            "pool_size": pool.get_size(),
            "pool_free": pool.get_idle_size(),
            "tables": [dict(t) for t in tables],
        }


# ── Case Records CRUD ────────────────────────────────────

async def add_case_record(case_id: int, title: str, record_type: str, content_text: str, file_name: str = "") -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO case_records (case_id, title, record_type, content_text, file_name)
               VALUES ($1, $2, $3, $4, $5) RETURNING *""",
            case_id, title, record_type, content_text, file_name,
        )
        return dict(row)


async def list_case_records(case_id: int) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM case_records WHERE case_id = $1 ORDER BY created_at DESC", case_id
        )
        return [dict(r) for r in rows]


async def get_case_record(record_id: int) -> dict | None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM case_records WHERE id = $1", record_id)
        return dict(row) if row else None


async def delete_case_record(record_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM case_records WHERE id = $1", record_id)
        return result.split()[-1] != "0"


async def get_case_records_text(case_id: int) -> str:
    """Concatenate all record texts for a case as LLM context."""
    records = await list_case_records(case_id)
    if not records:
        return ""
    parts = []
    for r in records:
        if r["content_text"].strip():
            parts.append(f"[{r['title']}]\n{r['content_text']}")
    return "\n\n".join(parts)


# ── Analysis History CRUD ─────────────────────────────────

async def save_analysis_history(case_id: int, focus: str, analysis_text: str) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO analysis_history (case_id, focus, analysis_text)
               VALUES ($1, $2, $3) RETURNING *""",
            case_id, focus, analysis_text,
        )
        return dict(row)


async def list_analysis_history(case_id: int) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM analysis_history WHERE case_id = $1 ORDER BY created_at DESC", case_id
        )
        return [dict(r) for r in rows]


async def list_simulation_sessions(case_id: int) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, case_id, mode, created_at FROM simulation_sessions WHERE case_id = $1 ORDER BY created_at DESC",
            case_id,
        )
        return [dict(r) for r in rows]


# ── Generated Documents CRUD ─────────────────────────────

async def save_generated_document(case_id: int, doc_type: str, doc_title: str, content: str) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO generated_documents (case_id, doc_type, doc_title, content)
               VALUES ($1, $2, $3, $4) RETURNING *""",
            case_id, doc_type, doc_title, content,
        )
        return dict(row)


async def list_generated_documents(case_id: int) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM generated_documents WHERE case_id = $1 ORDER BY created_at DESC", case_id
        )
        return [dict(r) for r in rows]


async def get_generated_document(doc_id: int) -> dict | None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM generated_documents WHERE id = $1", doc_id)
        return dict(row) if row else None


async def delete_generated_document(doc_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM generated_documents WHERE id = $1", doc_id)
        return result.split()[-1] != "0"


# ── LLM Config CRUD ──────────────────────────────────────

async def get_llm_config() -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM llm_config WHERE id = 1")
        if row:
            return dict(row)
        return {"provider": "ollama", "base_url": "", "api_key": "", "model": "",
                "context_window": 20000, "timeout": 3600}


async def update_llm_config(provider: str, base_url: str, api_key: str,
                             model: str, context_window: int, timeout: int) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE llm_config
               SET provider=$1, base_url=$2, api_key=$3, model=$4,
                   context_window=$5, timeout=$6, updated_at=NOW()
               WHERE id=1 RETURNING *""",
            provider, base_url, api_key, model, context_window, timeout,
        )
        return dict(row)


async def get_past_context(case_id: int, max_chars: int = 6000) -> str:
    """Build a summary of past simulations and analyses for LLM context enrichment."""
    pool = await _get_pool()
    parts = []
    async with pool.acquire() as conn:
        analyses = await conn.fetch(
            "SELECT focus, analysis_text, created_at FROM analysis_history WHERE case_id = $1 ORDER BY created_at DESC LIMIT 3",
            case_id,
        )
        for a in analyses:
            text = a["analysis_text"][:2000]
            parts.append(f"[历史分析 - {a['focus']}]\n{text}")

        sessions = await conn.fetch(
            "SELECT mode, messages, created_at FROM simulation_sessions WHERE case_id = $1 ORDER BY created_at DESC LIMIT 2",
            case_id,
        )
        for s in sessions:
            msgs = s["messages"]
            if isinstance(msgs, str):
                msgs = json.loads(msgs)
            summary_parts = []
            for m in msgs[-6:]:
                role = "用户" if m["role"] == "user" else "AI"
                summary_parts.append(f"{role}: {m['content'][:300]}")
            if summary_parts:
                parts.append(f"[历史模拟 - {s['mode']}]\n" + "\n".join(summary_parts))

    result = "\n\n---\n\n".join(parts)
    return result[:max_chars] if result else ""
