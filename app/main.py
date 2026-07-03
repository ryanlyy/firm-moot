import os
import time
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from openai import AsyncOpenAI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import (
    init_db, close_db, save_case, get_case, list_cases, update_case, delete_case,
    get_db_stats, get_db_health, list_users, update_user, delete_user,
    get_backup_schedule, update_backup_schedule,
    get_admin_statistics,
    add_case_record, list_case_records, get_case_record, delete_case_record,
    list_analysis_history, list_simulation_sessions,
    list_generated_documents, get_generated_document, delete_generated_document,
    get_llm_config, update_llm_config,
)
from app.models import (
    CaseCreate, CaseUpdate, SimulationRequest, SimulationResponse,
    AnalysisRequest, AnalysisResponse, DocumentRequest,
    UserRegister, UserLogin, UserUpdate, TokenResponse,
    BackupSchedule,
)
from app.auth import register_user, login_user, require_user, require_admin
from app.simulation import run_simulation, run_analysis, generate_document
from app.backup import (
    create_backup, restore_backup, list_backups, delete_backup,
    get_backup_filepath, scheduled_backup,
)

_scheduler = AsyncIOScheduler()
_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _load_llm_from_db()
    await _init_scheduler()
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)
    await close_db()


async def _load_llm_from_db():
    """Load LLM config from database, fall back to .env, then PROVIDERS defaults."""
    from app.llm import PROVIDERS, set_config, _env_config
    env = _env_config()
    db_cfg = await get_llm_config()
    has_db_data = bool(db_cfg.get("base_url") or db_cfg.get("model"))

    if has_db_data:
        provider = db_cfg.get("provider") or env["provider"]
        meta = PROVIDERS.get(provider, PROVIDERS["ollama"])
        base_url = db_cfg.get("base_url") or env["base_url"] or meta["base_url"]
        if provider == "ollama" and not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        set_config({
            "provider": provider,
            "base_url": base_url,
            "api_key": db_cfg.get("api_key") or env["api_key"] or meta["default_key"],
            "model": db_cfg.get("model") or env["model"] or meta["default_model"],
            "context_window": db_cfg.get("context_window") or env["context_window"],
            "timeout": db_cfg.get("timeout") or env["timeout"],
        })
    else:
        set_config(env)


app = FastAPI(title="AI 模拟法庭", version="2.1.0", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def _load_site_config() -> dict:
    from dotenv import dotenv_values
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    vals = dotenv_values(env_path)
    firm_logo = vals.get("FIRM_LOGO", os.getenv("FIRM_LOGO", "")).strip()
    logo_url = ""
    if firm_logo:
        logo_path = os.path.join(STATIC_DIR, firm_logo)
        if os.path.isfile(logo_path):
            logo_url = f"/static/{firm_logo}"
    return {
        "firm_name": vals.get("FIRM_NAME", os.getenv("FIRM_NAME", "")),
        "firm_logo": logo_url,
    }


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/site-config")
async def api_site_config():
    return _load_site_config()


# ── Auth ─────────────────────────────────────────────────

@app.post("/api/admin/create-user")
async def api_create_user(req: UserRegister, _: dict = Depends(require_admin)):
    user = await register_user(req.username, req.password, req.display_name, req.role.value)
    return user


@app.post("/api/auth/login", response_model=TokenResponse)
async def api_login(req: UserLogin):
    user, token = await login_user(req.username, req.password)
    return {"access_token": token, "user": user}


@app.get("/api/auth/me")
async def api_me(user: dict = Depends(require_user)):
    return user


# ── Case Management ─────────────────────────────────────

@app.post("/api/cases")
async def create_case(case: CaseCreate, user: dict = Depends(require_user)):
    data = case.model_dump()
    data["user_id"] = user["id"]
    case_id = await save_case(data)
    saved = await get_case(case_id)
    return saved


@app.get("/api/cases")
async def get_cases(user: dict = Depends(require_user)):
    if user["role"] == "admin":
        return await list_cases()
    return await list_cases(user_id=user["id"])


@app.get("/api/cases/{case_id}")
async def get_case_detail(case_id: int, user: dict = Depends(require_user)):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权访问此案件")
    return case


@app.put("/api/cases/{case_id}")
async def api_update_case(case_id: int, req: CaseUpdate, user: dict = Depends(require_user)):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权修改此案件")
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if hasattr(fields.get("case_type", None), "value"):
        fields["case_type"] = fields["case_type"].value
    if hasattr(fields.get("our_role", None), "value"):
        fields["our_role"] = fields["our_role"].value
    updated = await update_case(case_id, **fields)
    if not updated:
        raise HTTPException(404, "更新失败")
    return updated


@app.delete("/api/cases/{case_id}")
async def remove_case(case_id: int, user: dict = Depends(require_user)):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权删除此案件")
    await delete_case(case_id)
    return {"ok": True}


# ── Simulation ───────────────────────────────────────────

@app.post("/api/simulate", response_model=SimulationResponse)
async def simulate(req: SimulationRequest, user: dict = Depends(require_user)):
    case = await get_case(req.case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权操作此案件")
    try:
        return await run_simulation(
            case_id=req.case_id, mode=req.mode,
            user_message=req.user_message, session_id=req.session_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"模拟出错: {e}")


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze(req: AnalysisRequest, user: dict = Depends(require_user)):
    case = await get_case(req.case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权操作此案件")
    try:
        return await run_analysis(case_id=req.case_id, focus=req.focus)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"分析出错: {e}")


# ── Case Records ─────────────────────────────────────────

def _extract_text_from_docx(file_bytes: bytes) -> str:
    import io
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


@app.post("/api/cases/{case_id}/records")
async def api_add_record(
    case_id: int,
    title: str = Form(...),
    record_type: str = Form("hearing"),
    content_text: str = Form(""),
    file: UploadFile | None = File(None),
    user: dict = Depends(require_user),
):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权操作此案件")

    file_name = ""
    extracted = content_text

    if file and file.filename:
        file_name = file.filename
        raw = await file.read()
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext in ("docx",):
            try:
                extracted = _extract_text_from_docx(raw)
            except Exception as e:
                raise HTTPException(400, f"Word 文件解析失败: {e}")
        elif ext in ("txt", "md"):
            extracted = raw.decode("utf-8", errors="replace")
        elif not content_text:
            extracted = f"[已上传文件: {file.filename}，请手动补充文字记录]"

    if not extracted.strip():
        raise HTTPException(400, "请提供文字内容或上传文件")

    record = await add_case_record(case_id, title, record_type, extracted, file_name)
    return record


@app.get("/api/cases/{case_id}/records")
async def api_list_records(case_id: int, user: dict = Depends(require_user)):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权访问")
    return await list_case_records(case_id)


@app.delete("/api/records/{record_id}")
async def api_delete_record(record_id: int, user: dict = Depends(require_user)):
    record = await get_case_record(record_id)
    if not record:
        raise HTTPException(404, "记录不存在")
    case = await get_case(record["case_id"])
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权删除")
    await delete_case_record(record_id)
    return {"ok": True}


# ── History ──────────────────────────────────────────────

@app.get("/api/cases/{case_id}/history")
async def api_case_history(case_id: int, user: dict = Depends(require_user)):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权访问")
    analyses = await list_analysis_history(case_id)
    sessions = await list_simulation_sessions(case_id)
    return {"analyses": analyses, "sessions": sessions}


# ── Document Generation ──────────────────────────────────

@app.post("/api/cases/{case_id}/generate-document")
async def api_generate_document(case_id: int, req: DocumentRequest, user: dict = Depends(require_user)):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权操作此案件")
    try:
        return await generate_document(case_id, req.doc_type)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"文书生成出错: {e}")


@app.get("/api/cases/{case_id}/documents")
async def api_list_documents(case_id: int, user: dict = Depends(require_user)):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权访问")
    return await list_generated_documents(case_id)


@app.get("/api/documents/{doc_id}")
async def api_get_document(doc_id: int, user: dict = Depends(require_user)):
    doc = await get_generated_document(doc_id)
    if not doc:
        raise HTTPException(404, "文书不存在")
    case = await get_case(doc["case_id"])
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权访问")
    return doc


@app.delete("/api/documents/{doc_id}")
async def api_delete_document(doc_id: int, user: dict = Depends(require_user)):
    doc = await get_generated_document(doc_id)
    if not doc:
        raise HTTPException(404, "文书不存在")
    case = await get_case(doc["case_id"])
    if user["role"] != "admin" and case["user_id"] != user["id"]:
        raise HTTPException(403, "无权删除")
    await delete_generated_document(doc_id)
    return {"ok": True}


# ── Admin: User Management ──────────────────────────────

@app.get("/api/admin/users")
async def api_list_users(_: dict = Depends(require_admin)):
    return await list_users()


@app.put("/api/admin/users/{user_id}")
async def api_update_user(user_id: int, req: UserUpdate, _: dict = Depends(require_admin)):
    fields = {}
    if req.display_name is not None:
        fields["display_name"] = req.display_name
    if req.role is not None:
        fields["role"] = req.role.value
    updated = await update_user(user_id, **fields)
    if not updated:
        raise HTTPException(404, "用户不存在")
    return updated


@app.delete("/api/admin/users/{user_id}")
async def api_delete_user(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "不能删除自己")
    ok = await delete_user(user_id)
    if not ok:
        raise HTTPException(404, "用户不存在")
    return {"ok": True}


# ── Admin: Monitoring ────────────────────────────────────

@app.get("/api/admin/monitor")
async def api_monitor(_: dict = Depends(require_admin)):
    stats = await get_db_stats()
    stats["uptime_seconds"] = int(time.time() - _start_time)
    return stats


@app.get("/api/admin/db-health")
async def api_db_health(_: dict = Depends(require_admin)):
    return await get_db_health()


@app.get("/api/admin/statistics")
async def api_statistics(_: dict = Depends(require_admin)):
    return await get_admin_statistics()


# ── Admin: Backup & Restore ─────────────────────────────

@app.post("/api/admin/backup")
async def api_create_backup(_: dict = Depends(require_admin)):
    try:
        return await create_backup()
    except Exception as e:
        raise HTTPException(500, f"备份失败: {e}")


@app.get("/api/admin/backups")
async def api_list_backups(_: dict = Depends(require_admin)):
    return list_backups()


@app.post("/api/admin/restore/{filename}")
async def api_restore(filename: str, _: dict = Depends(require_admin)):
    try:
        await restore_backup(filename)
        return {"ok": True, "message": f"已从 {filename} 恢复"}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"恢复失败: {e}")


@app.delete("/api/admin/backups/{filename}")
async def api_delete_backup(filename: str, _: dict = Depends(require_admin)):
    ok = delete_backup(filename)
    if not ok:
        raise HTTPException(404, "备份文件不存在")
    return {"ok": True}


@app.get("/api/admin/backups/{filename}/download")
async def api_download_backup(filename: str, _: dict = Depends(require_admin)):
    path = get_backup_filepath(filename)
    if not path:
        raise HTTPException(404, "备份文件不存在")
    return FileResponse(path, filename=filename, media_type="application/sql")


@app.get("/api/admin/backup-schedule")
async def api_get_schedule(_: dict = Depends(require_admin)):
    return await get_backup_schedule()


@app.put("/api/admin/backup-schedule")
async def api_update_schedule(req: BackupSchedule, _: dict = Depends(require_admin)):
    result = await update_backup_schedule(req.enabled, req.cron_hour, req.cron_minute, req.keep_count)
    await _init_scheduler()
    return result


# ── Admin: LLM Configuration ─────────────────────────────

@app.get("/api/admin/llm-providers")
async def api_llm_providers(_: dict = Depends(require_admin)):
    from app.llm import PROVIDERS
    return {k: {"label": v["label"], "default_model": v["default_model"],
                "base_url": v["base_url"], "needs_key": v["needs_key"],
                "models": v.get("models", [])}
            for k, v in PROVIDERS.items()}


@app.get("/api/admin/llm-models/{provider}")
async def api_llm_models(provider: str, _: dict = Depends(require_admin)):
    from app.llm import list_models, get_config
    cfg = get_config()
    base_url = cfg.get("base_url") if provider == cfg.get("provider") else None
    models = await list_models(provider, base_url)
    return {"provider": provider, "models": models}


@app.get("/api/admin/llm-config")
async def api_get_llm_config(_: dict = Depends(require_admin)):
    from app.llm import get_config
    active = get_config()
    key = active.get("api_key", "")
    masked_key = ""
    if key and len(key) > 8:
        masked_key = key[:4] + "****" + key[-4:]
    elif key:
        masked_key = "****"
    base_url = active.get("base_url", "")
    if base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/")[:-3].rstrip("/")
    return {
        "provider": active.get("provider", "ollama"),
        "base_url": base_url,
        "api_key_masked": masked_key,
        "model": active.get("model", ""),
        "context_window": active.get("context_window", 20000),
        "timeout": active.get("timeout", 3600),
    }


@app.post("/api/admin/llm-test")
async def api_test_llm(_: dict = Depends(require_admin)):
    """Send a minimal request to verify LLM connectivity."""
    from app.llm import get_config, PROVIDERS
    cfg = get_config()
    provider = cfg.get("provider", "ollama")
    meta = PROVIDERS.get(provider, PROVIDERS["ollama"])
    try:
        if meta["sdk"] == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic(
                api_key=cfg["api_key"], timeout=15.0,
            )
            resp = await client.messages.create(
                model=cfg["model"], max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}],
            )
            return {"ok": True, "provider": provider, "model": cfg["model"],
                    "message": "连接成功，模型可用"}
        else:
            client = AsyncOpenAI(
                api_key=cfg["api_key"] or "no-key",
                base_url=cfg["base_url"],
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
            resp = await client.chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            return {"ok": True, "provider": provider, "model": cfg["model"],
                    "message": "连接成功，模型可用"}
    except Exception as e:
        err_msg = str(e)
        if len(err_msg) > 200:
            err_msg = err_msg[:200] + "..."
        return {"ok": False, "provider": provider, "model": cfg["model"],
                "message": f"连接失败: {err_msg}"}


@app.put("/api/admin/llm-config")
async def api_update_llm_config(req: dict, _: dict = Depends(require_admin)):
    from app.llm import PROVIDERS, set_config
    provider = req.get("provider", "ollama")
    if provider not in PROVIDERS:
        raise HTTPException(400, f"不支持的模型提供商: {provider}")
    meta = PROVIDERS[provider]
    api_key = req.get("api_key", "")
    if api_key == "" or "****" in api_key:
        existing = await get_llm_config()
        api_key = existing.get("api_key", "")
    base_url = req.get("base_url", "") or meta["base_url"]
    model = req.get("model", "") or meta["default_model"]
    context_window = int(req.get("context_window", 20000))
    timeout = int(req.get("timeout", 3600))

    result = await update_llm_config(provider, base_url, api_key, model, context_window, timeout)

    effective_base = base_url
    if provider == "ollama" and not effective_base.rstrip("/").endswith("/v1"):
        effective_base = effective_base.rstrip("/") + "/v1"
    set_config({
        "provider": provider,
        "base_url": effective_base,
        "api_key": api_key or meta["default_key"],
        "model": model,
        "context_window": context_window,
        "timeout": timeout,
    })
    return {"ok": True, "provider": provider, "model": model}


async def _init_scheduler():
    _scheduler.remove_all_jobs()
    schedule = await get_backup_schedule()
    if schedule.get("enabled", True):
        _scheduler.add_job(
            scheduled_backup,
            CronTrigger(hour=schedule["cron_hour"], minute=schedule["cron_minute"]),
            id="auto_backup",
            replace_existing=True,
        )
