"""Apply pending SQL migrations from supabase/migrations to a database, once each, in order.

Usage:
  uv run --project server python scripts/migrate.py                    # DATABASE_URL from .env (local)
  uv run --project server python scripts/migrate.py --env SUPABASE_DATABASE_URL   # the hosted database

Applied files are recorded in a schema_migrations table. A database created before this table existed is detected:
0001_init.sql is marked as applied when its tables are already there.
"""

import argparse
import re
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"


def env_value(name: str) -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        m = re.match(rf"\s*{re.escape(name)}\s*=\s*(.*)", line)
        if m and m.group(1).strip():
            return m.group(1).strip()
    raise SystemExit(f"{name} is not set in .env")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env", default="DATABASE_URL", help="which .env variable holds the connection string")
    a = p.parse_args()
    with psycopg.connect(env_value(a.env), autocommit=True) as conn:
        conn.execute("create table if not exists schema_migrations (name text primary key, applied_at timestamptz not null default now())")
        conn.execute("alter table schema_migrations enable row level security")
        applied = {r[0] for r in conn.execute("select name from schema_migrations")}
        if "0001_init.sql" not in applied and conn.execute("select to_regclass('public.lectures')").fetchone()[0]:
            conn.execute("insert into schema_migrations (name) values ('0001_init.sql')")
            applied.add("0001_init.sql")
        pending = [f for f in sorted(MIGRATIONS.glob("*.sql")) if f.name not in applied]
        for f in pending:
            with conn.transaction():
                conn.execute(f.read_text())
                conn.execute("insert into schema_migrations (name) values (%s)", (f.name,))
            print(f"applied {f.name}")
        print(f"{a.env}: up to date ({len(applied) + len(pending)} migrations)")


if __name__ == "__main__":
    main()
