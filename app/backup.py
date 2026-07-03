import asyncio
import os
import glob
import time
from datetime import datetime
from urllib.parse import urlparse

from app.database import DATABASE_URL, get_backup_schedule

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups")


def _ensure_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _parse_db_url() -> dict:
    parsed = urlparse(DATABASE_URL)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "lawemu",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "lawemu",
    }


def _find_pg_dump() -> str:
    candidates = [
        "pg_dump",
        r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
    ]
    for c in candidates:
        if os.path.isfile(c) or c == "pg_dump":
            return c
    return "pg_dump"


async def create_backup() -> dict:
    _ensure_dir()
    db = _parse_db_url()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{ts}.sql"
    filepath = os.path.join(BACKUP_DIR, filename)
    pg_dump = _find_pg_dump()

    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    proc = await asyncio.create_subprocess_exec(
        pg_dump,
        "-h", db["host"], "-p", db["port"], "-U", db["user"],
        "-d", db["dbname"], "-F", "p", "--clean", "--if-exists",
        "-f", filepath,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {stderr.decode()}")

    stat = os.stat(filepath)
    return {
        "filename": filename,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


async def restore_backup(filename: str):
    filepath = os.path.join(BACKUP_DIR, filename)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"备份文件不存在: {filename}")

    db = _parse_db_url()
    psql = _find_pg_dump().replace("pg_dump", "psql")

    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    proc = await asyncio.create_subprocess_exec(
        psql,
        "-h", db["host"], "-p", db["port"], "-U", db["user"],
        "-d", db["dbname"], "-f", filepath,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode()
        if "ERROR" in err:
            raise RuntimeError(f"restore failed: {err}")


def list_backups() -> list[dict]:
    _ensure_dir()
    files = glob.glob(os.path.join(BACKUP_DIR, "backup_*.sql"))
    result = []
    for f in sorted(files, reverse=True):
        stat = os.stat(f)
        result.append({
            "filename": os.path.basename(f),
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return result


def delete_backup(filename: str) -> bool:
    filepath = os.path.join(BACKUP_DIR, filename)
    if os.path.isfile(filepath):
        os.remove(filepath)
        return True
    return False


def get_backup_filepath(filename: str) -> str | None:
    filepath = os.path.join(BACKUP_DIR, filename)
    return filepath if os.path.isfile(filepath) else None


async def cleanup_old_backups(keep_count: int = 7):
    backups = list_backups()
    for b in backups[keep_count:]:
        delete_backup(b["filename"])


async def scheduled_backup():
    """Called by APScheduler."""
    try:
        await create_backup()
        schedule = await get_backup_schedule()
        await cleanup_old_backups(schedule.get("keep_count", 7))
    except Exception as e:
        print(f"[Scheduled Backup Error] {e}")
