from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.config import Settings
from tests.conftest import Db, seed_lecture

pytestmark = pytest.mark.db


async def test_health(anon: httpx.AsyncClient) -> None:
    assert (await anon.get("/health")).json() == {"status": "ok"}


async def test_login_sets_httponly_lax_cookie_and_me_works(anon: httpx.AsyncClient) -> None:
    response = await anon.post("/auth/demo-login", json={"user_id": "u_sam"})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = (await anon.get("/auth/me")).json()
    assert me["id"] == "u_sam" and me["role"] == "student"
    assert (await anon.post("/auth/logout")).status_code == 204
    assert (await anon.get("/auth/me")).status_code == 401


async def test_unknown_user_and_tampered_cookie_rejected(anon: httpx.AsyncClient) -> None:
    assert (await anon.post("/auth/demo-login", json={"user_id": "nobody"})).status_code == 400
    anon.cookies.set("bn_session", "forged")
    assert (await anon.get("/auth/me")).status_code == 401


async def test_cors_allows_the_web_app_with_credentials(anon: httpx.AsyncClient) -> None:
    response = await anon.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_students_get_403_on_lecturer_routes(sam: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db)
    assert (await sam.get("/review")).status_code == 403
    assert (await sam.post("/review/bullet:bul_2/decision", json={"decision": "approve"})).status_code == 403
    assert (await sam.post("/uploads", json={"filename": "a.mp4", "size_bytes": 5, "title": "t"})).status_code == 403
    assert (await sam.get("/uploads/up_x")).status_code == 403
    assert (await sam.get("/lectures/lec_1/progress")).status_code == 403


async def test_anonymous_gets_401(anon: httpx.AsyncClient) -> None:
    assert (await anon.get("/lectures")).status_code == 401
    assert (await anon.get("/lectures/lec_1/progress")).status_code == 401


async def test_lecture_list_and_detail(sam: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db)
    listing = (await sam.get("/lectures")).json()
    assert [(x["id"], x["section_count"], x["open_items"]) for x in listing] == [("lec_1", 2, 2)]
    detail = (await sam.get("/lectures/lec_1")).json()
    assert [s["heading"] for s in detail["sections"]] == ["Row picture", "Elimination"]
    assert detail["sections"][1]["bullets"][0]["uncertain"] is True
    assert detail["pdf_url"] == "/lectures/lec_1/pdf"
    assert len(detail["board_blocks"]) == 2


async def test_students_only_see_summary_of_processing_lectures(sam: httpx.AsyncClient, lecturer: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db, status="processing")
    assert len((await sam.get("/lectures")).json()) == 1
    assert (await sam.get("/lectures/lec_1")).status_code == 409
    assert (await sam.get("/lectures/lec_1/video")).status_code == 409
    assert (await lecturer.get("/lectures/lec_1")).status_code == 200


async def test_failed_lectures_hidden_from_students(sam: httpx.AsyncClient, lecturer: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db, status="failed")
    assert (await sam.get("/lectures")).json() == []
    assert (await sam.get("/lectures/lec_1")).status_code == 404
    assert len((await lecturer.get("/lectures")).json()) == 1


async def test_bullet_source(sam: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db)
    source = (await sam.get("/bullets/bul_2/source")).json()
    assert [b["id"] for b in source["board_blocks"]] == ["b_2"]
    assert source["snapshot_urls"] == ["/snapshots/lec_1/b_2.jpg"]
    assert [t["text"] for t in source["transcript"]] == ["Welcome", "So x equals two y minus one"]
    assert (await sam.get("/bullets/nope/source")).status_code == 404


async def test_video_range_requests(sam: httpx.AsyncClient, db: Db, settings: Settings) -> None:
    await seed_lecture(db)
    video = settings.data_dir / "lectures" / "lec_1" / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(bytes(range(100)))
    await db.execute("update lectures set video_path = %s", (str(video),))
    full = await sam.get("/lectures/lec_1/video")
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    part = await sam.get("/lectures/lec_1/video", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == bytes(range(10, 20))
    assert part.headers["content-range"] == "bytes 10-19/100"


async def test_video_path_outside_data_dir_is_refused(sam: httpx.AsyncClient, db: Db, tmp_path: Path) -> None:
    await seed_lecture(db)
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"x")
    await db.execute("update lectures set video_path = %s", (str(outside),))
    assert (await sam.get("/lectures/lec_1/video")).status_code == 404


async def test_snapshot_is_cropped_and_cached(sam: httpx.AsyncClient, db: Db, settings: Settings) -> None:
    await seed_lecture(db, settings.data_dir)
    response = await sam.get("/snapshots/lec_1/b_1.jpg")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    cached = settings.data_dir / "lectures" / "lec_1" / "snapshots" / "b_1.jpg"
    assert cached.is_file()
    with Image.open(cached) as crop:
        assert crop.width < 200  # a crop, not the whole frame
    assert (await sam.get("/snapshots/lec_1/nope.jpg")).status_code == 404
    assert (await sam.get("/snapshots/lec_1/..%2Fx.jpg")).status_code in (404, 422)
