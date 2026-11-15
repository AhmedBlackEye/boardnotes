"""Run the BoardNotes API for the browser tests, offline, on a throwaway database.

Started by playwright.config.ts (webServer). It:
1. creates `boardnotes_e2e_<random>` next to the local database and applies supabase/migrations to it,
2. runs `uvicorn app.main:app` with fake models (LLM_MODE=fake, TRANSCRIBER=fixture) and a temporary data folder,
3. drops the database and deletes the folder when it is stopped (Ctrl-C / SIGTERM from Playwright).

The main `boardnotes` database is only used to run `create database` / `drop database`; nothing in it is read or written.

Usage: uv run --project ../server python e2e/api_server.py [--port 8010] [--web-origin http://localhost:3010]
"""

import argparse
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from types import FrameType
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "server"
# Deliberately not read from .env: that may point at the hosted database.
ADMIN_URL = os.environ.get("E2E_ADMIN_DATABASE_URL", "postgresql://boardnotes:boardnotes@localhost:5433/boardnotes")


def with_db(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


def create_db(admin: psycopg.Connection, name: str) -> str:
    url = with_db(ADMIN_URL, name)
    admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    with psycopg.connect(url, autocommit=True) as conn:
        for migration in sorted((REPO / "supabase" / "migrations").glob("*.sql")):
            conn.execute(migration.read_text().encode())
    return url


def offline_env(db_url: str, data_dir: Path, web_origin: str) -> dict[str, str]:
    """Environment for the API: these override anything in .env, so no real model or speech API can be reached."""
    return {
        **os.environ,
        "DATABASE_URL": db_url,
        "DATA_DIR": str(data_dir),
        "LLM_MODE": "fake",
        "TRANSCRIBER": "fixture",
        "ANTHROPIC_API_KEY": "",
        "ELEVENLABS_API_KEY": "",
        "FAL_API_KEY": "",
        "FAL_KEY": "",
        "DEMO_LOGIN": "true",
        "SESSION_SECRET": secrets.token_urlsafe(32),
        "WEB_ORIGINS": web_origin,
        "PUBLIC_BASE_URL": web_origin,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8010)
    p.add_argument("--web-origin", default="http://localhost:3010")
    a = p.parse_args()

    name = f"boardnotes_e2e_{secrets.token_hex(4)}"
    data_dir = Path(tempfile.mkdtemp(prefix="boardnotes-e2e-"))
    admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=5)
    child: subprocess.Popen[bytes] | None = None

    def stop(signum: int, _frame: FrameType | None) -> None:
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)
        else:
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        url = create_db(admin, name)
        print(f"e2e database {name}, data in {data_dir}", flush=True)
        cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(a.port), "--no-access-log"]
        child = subprocess.Popen(cmd, cwd=SERVER, env=offline_env(url, data_dir, a.web_origin))  # noqa: S603 - fixed command
        return child.wait()  # a stop signal forwards SIGINT to uvicorn, which shuts down and returns here
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
        admin.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))
        admin.close()
        shutil.rmtree(data_dir, ignore_errors=True)
        print(f"dropped {name}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
