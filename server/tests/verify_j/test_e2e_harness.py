"""V2 tests for J (I-3): the browser-test harness, checked from the spec.

Spec: offline (no keys, fake models), throwaway database that is dropped afterwards, never the dev ports,
roles enforced on the server (students get 403 on lecturer routes), demo users usable for both flows.
"""

import importlib.util
import json
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import httpx
import psycopg
import pytest

REPO = Path(__file__).resolve().parents[3]
E2E = REPO / "web" / "e2e"
ADMIN = "postgresql://boardnotes:boardnotes@localhost:5433/boardnotes"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("e2e_api_server", E2E / "api_server.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod() -> ModuleType:
    return _load()


def _db_exists(name: str) -> bool:
    with psycopg.connect(ADMIN, autocommit=True, connect_timeout=3) as c:
        return c.execute("select 1 from pg_database where datname=%s", (name,)).fetchone() is not None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ---------- offline environment ----------
def test_offline_env_has_no_keys_and_fake_models(mod: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_API_KEY", "FAL_KEY"):
        monkeypatch.setenv(k, "sk-real-looking-secret")
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("TRANSCRIBER", "elevenlabs")
    env = mod.offline_env("postgresql://x/y", tmp_path, "http://localhost:3010")
    assert env["LLM_MODE"] == "fake"
    assert env["TRANSCRIBER"] == "fixture"
    for k in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_API_KEY", "FAL_KEY"):
        assert env[k] == ""
    assert env["DATABASE_URL"] == "postgresql://x/y"
    assert env["DATA_DIR"] == str(tmp_path)
    assert env["WEB_ORIGINS"] == "http://localhost:3010"


def test_session_secret_is_random_per_call(mod: ModuleType, tmp_path: Path) -> None:
    a = mod.offline_env("u", tmp_path, "o")["SESSION_SECRET"]
    b = mod.offline_env("u", tmp_path, "o")["SESSION_SECRET"]
    assert a != b and len(a) >= 32


def test_with_db_swaps_only_the_database_name(mod: ModuleType) -> None:
    assert mod.with_db("postgresql://u:p@localhost:5433/boardnotes", "x1") == "postgresql://u:p@localhost:5433/x1"


def test_create_db_applies_migrations_then_drop(mod: ModuleType) -> None:
    name = f"boardnotes_vj_{secrets.token_hex(4)}"
    admin = psycopg.connect(ADMIN, autocommit=True, connect_timeout=3)
    try:
        url = mod.create_db(admin, name)
        assert url.endswith("/" + name)
        with psycopg.connect(url) as c:
            tables = {r[0] for r in c.execute("select table_name from information_schema.tables where table_schema='public'")}
        assert len(tables) >= 3, tables
    finally:
        admin.execute(f'drop database if exists "{name}" with (force)')
        admin.close()
    assert not _db_exists(name)


# ---------- static checks on the browser tests ----------
def test_ports_are_not_the_dev_ports() -> None:
    txt = (E2E / "ports.ts").read_text()
    web = re.search(r"WEB_PORT = (\d+)", txt)
    api = re.search(r"API_PORT = (\d+)", txt)
    assert web and api
    assert int(web.group(1)) != 3000 and int(api.group(1)) != 8000


def test_e2e_never_uses_real_model_keys() -> None:
    for f in E2E.glob("*"):
        if f.is_file():
            assert not re.search(r"sk-ant-|LLM_MODE\s*[:=]\s*[\"']?live", f.read_text()), f.name


def test_both_flows_and_roles_specs_cover_the_prototype() -> None:
    for name in ("student.spec.ts", "lecturer.spec.ts", "roles.spec.ts"):
        assert (E2E / name).is_file(), name
    assert "403" in (E2E / "roles.spec.ts").read_text()
    lect = (E2E / "lecturer.spec.ts").read_text()
    for step in ("Upload lecture", "Review queue", "View as student", "Download PDF"):
        assert step in lect
    stud = (E2E / "student.spec.ts").read_text()
    for step in ("Suggest a fix", "Upvote", "Ask the lecture", "Course notes"):
        assert step in stud


def test_make_e2e_target_and_package_script() -> None:
    assert re.search(r"^e2e:", (REPO / "Makefile").read_text(), re.M)
    pkg = json.loads((REPO / "web" / "package.json").read_text())
    assert "test:e2e" in pkg["scripts"]


# ---------- the harness for real: start it, check roles over HTTP, stop it, database is dropped ----------
@pytest.fixture(scope="module")
def running() -> Iterator[tuple[str, str]]:
    port = _free_port()
    p = subprocess.Popen(
        [sys.executable, str(E2E / "api_server.py"), "--port", str(port), "--web-origin", "http://localhost:3999"],
        cwd=REPO / "server",
        stdout=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    name = ""
    try:
        assert p.stdout
        line = p.stdout.readline()
        m = re.search(r"e2e database (\S+),", line)
        assert m, line
        name = m.group(1)
        for _ in range(100):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            pytest.fail("api did not start")
        yield base, name
    finally:
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            p.kill()
    assert not _db_exists(name), "throwaway database was not dropped"


def _login(base: str, uid: str) -> httpx.Client:
    c = httpx.Client(base_url=base)
    r = c.post("/auth/demo-login", json={"user_id": uid})
    assert r.status_code == 200, r.text
    return c


def test_student_is_forbidden_on_lecturer_routes(running: tuple[str, str]) -> None:
    base, _ = running
    s = _login(base, "u_sam")
    assert s.get("/review").status_code == 403
    assert s.post("/uploads", json={"filename": "x.mp4", "size_bytes": 10, "title": "x"}).status_code == 403
    assert s.post("/review/bullet:bul_x/decision", json={"decision": "approve"}).status_code == 403


def test_anonymous_is_rejected(running: tuple[str, str]) -> None:
    base, _ = running
    c = httpx.Client(base_url=base)
    assert c.get("/review").status_code in (401, 403)
    assert c.get("/lectures").status_code in (401, 403)


def test_lecturer_can_reach_review_and_lectures(running: tuple[str, str]) -> None:
    base, _ = running
    c = _login(base, "u_lecturer")
    assert c.get("/review").status_code == 200
    assert c.get("/lectures").status_code == 200
    assert _login(base, "u_sam").get("/lectures").status_code == 200


def test_cors_allows_only_the_given_web_origin(running: tuple[str, str]) -> None:
    base, _ = running
    hdr = {"Access-Control-Request-Method": "GET"}
    ok = httpx.options(base + "/lectures", headers={**hdr, "Origin": "http://localhost:3999"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3999"
    bad = httpx.options(base + "/lectures", headers={**hdr, "Origin": "http://evil.example"})
    assert bad.headers.get("access-control-allow-origin") in (None, "")


def test_demo_login_rejects_unknown_user(running: tuple[str, str]) -> None:
    base, _ = running
    r = httpx.post(base + "/auth/demo-login", json={"user_id": "u_nobody"})
    assert r.status_code in (400, 401, 403, 404, 422)
