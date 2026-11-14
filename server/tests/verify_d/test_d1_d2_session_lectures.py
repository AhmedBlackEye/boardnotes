"""D-1 (session, roles) and D-2 (lecture endpoints, source view, snapshots, video Range)."""

import httpx
import pytest

from app.contracts.api import LectureDetail, LectureSummary, Me, SourceView

from .conftest import seed

pytestmark = pytest.mark.asyncio


# ---------- D-1 ----------
@pytest.mark.parametrize(("uid", "role"), [("u_lecturer", "lecturer"), ("u_sam", "student"), ("u_riya", "student"), ("u_tom", "student")])
async def test_login_each_seeded_user(app, uid, role):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/demo-login", json={"user_id": uid})
        assert r.status_code == 200
        me = Me.model_validate((await c.get("/auth/me")).json())
        assert me.id == uid and me.role == role


async def test_unknown_user_cannot_login(anon):
    r = await anon.post("/auth/demo-login", json={"user_id": "u_nobody"})
    assert 400 <= r.status_code < 500
    assert (await anon.get("/auth/me")).status_code == 401


async def test_login_rejects_extra_fields(anon):
    r = await anon.post("/auth/demo-login", json={"user_id": "u_sam", "role": "lecturer"})
    assert r.status_code == 422


async def test_anonymous_gets_401_on_protected_routes(anon, db):
    await seed(db)
    for path in ("/lectures", "/lectures/lec_1", "/bullets/bul_1/source", "/lectures/lec_1/video", "/review", "/pdfs", "/module/pdf"):
        assert (await anon.get(path)).status_code == 401, path
    assert (await anon.post("/lectures/lec_1/ask", json={"question": "hi"})).status_code == 401
    assert (await anon.post("/suggestions", json={"bullet_id": "bul_1", "proposed_text": "x"})).status_code == 401


async def test_forged_and_tampered_cookie_rejected(app, sam):
    cookie_name = next(iter(sam.cookies.keys()))
    value = sam.cookies[cookie_name]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        c.cookies.set(cookie_name, "u_lecturer")
        assert (await c.get("/auth/me")).status_code == 401
        c.cookies.set(cookie_name, value[:-2] + ("aa" if not value.endswith("aa") else "bb"))
        assert (await c.get("/auth/me")).status_code == 401


async def test_logout_clears_session(sam):
    assert (await sam.get("/auth/me")).status_code == 200
    assert (await sam.post("/auth/logout")).status_code in (200, 204)
    assert (await sam.get("/auth/me")).status_code == 401


async def test_student_403_on_lecturer_routes(sam, db):
    await seed(db)
    assert (await sam.get("/review")).status_code == 403
    assert (await sam.post("/review/sug_x/decision", json={"decision": "approve"})).status_code in (403,)
    assert (await sam.post("/uploads", json={"filename": "a.mp4", "size_bytes": 10, "title": "t"})).status_code == 403
    assert (await sam.put("/uploads/up_x", content=b"x", headers={"Content-Range": "bytes 0-0/1"})).status_code == 403
    assert (await sam.post("/uploads/up_x/complete")).status_code == 403


async def test_lecturer_can_reach_lecturer_routes(lecturer, db):
    await seed(db)
    assert (await lecturer.get("/review")).status_code == 200


# ---------- D-2 ----------
async def test_lecture_list_matches_contract(sam, db):
    await seed(db)
    r = await sam.get("/lectures")
    assert r.status_code == 200
    items = [LectureSummary.model_validate(x) for x in r.json()]
    lec = next(i for i in items if i.id == "lec_1")
    assert lec.title == "Linear systems"
    assert lec.section_count == 2
    assert lec.duration_s == 200


async def test_lecture_detail_matches_contract(sam, db, settings):
    await seed(db, settings.data_dir)
    r = await sam.get("/lectures/lec_1")
    assert r.status_code == 200
    d = LectureDetail.model_validate(r.json())
    assert [s.id for s in d.sections] == ["sec_1", "sec_2"]
    assert [b.text for b in d.sections[1].bullets] == ["x = 2y + 1", "Subtract the rows"]
    assert d.sections[1].bullets[0].uncertain is True  # 0.5 < LOW_CONFIDENCE
    assert d.sections[0].bullets[0].uncertain is False
    assert d.sections[0].bullets[0].board_block_ids == ["b_1"]
    assert d.sections[0].bullets[0].transcript_ranges[0].start_s == 10
    assert {b.id for b in d.board_blocks} == {"b_1", "b_2"}
    assert d.video_url


async def test_unknown_lecture_404(sam):
    assert (await sam.get("/lectures/nope")).status_code == 404
    assert (await sam.get("/bullets/nope/source")).status_code == 404


async def test_open_items_counts_open_fixes_and_uncertain(lecturer, sam, db):
    await seed(db)
    base = {x["id"]: x for x in (await lecturer.get("/lectures")).json()}["lec_1"]["open_items"]
    assert base >= 2  # bul_2 and bul_3 are uncertain
    r = await sam.post("/suggestions", json={"bullet_id": "bul_1", "proposed_text": "Each equation is a straight line"})
    assert r.status_code == 201
    after = {x["id"]: x for x in (await lecturer.get("/lectures")).json()}["lec_1"]["open_items"]
    assert after == base + 1


async def test_source_view(sam, db, settings):
    await seed(db, settings.data_dir)
    r = await sam.get("/bullets/bul_1/source")
    assert r.status_code == 200
    sv = SourceView.model_validate(r.json())
    assert sv.bullet_id == "bul_1"
    assert [b.id for b in sv.board_blocks] == ["b_1"]
    assert len(sv.snapshot_urls) == 1
    # transcript lines overlap the 10-30 s range only (times are seconds)
    texts = [t.text for t in sv.transcript]
    assert "So x equals two y minus one" in texts
    assert "Now elimination" not in texts
    assert all(isinstance(t.start_s, float | int) for t in sv.transcript)


async def test_snapshot_served_as_jpeg(sam, db, settings):
    await seed(db, settings.data_dir)
    sv = SourceView.model_validate((await sam.get("/bullets/bul_1/source")).json())
    r = await sam.get(sv.snapshot_urls[0])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert r.content[:2] == b"\xff\xd8"


async def test_snapshot_unknown_and_traversal(sam, db, settings):
    await seed(db, settings.data_dir)
    assert (await sam.get("/snapshots/lec_1/nope.jpg")).status_code == 404
    assert (await sam.get("/snapshots/lec_1/..%2F..%2Fetc%2Fpasswd.jpg")).status_code in (400, 404)
    assert (await sam.get("/snapshots/..%2F/b_1.jpg")).status_code in (400, 404)


@pytest.fixture
async def with_video(db, settings):
    await seed(db, settings.data_dir)
    f = settings.data_dir / "v.mp4"
    f.write_bytes(bytes(range(256)) * 4)  # 1024 bytes
    await db.execute("update lectures set video_path=%s, playback_path=%s where id='lec_1'", (str(f), str(f)))
    return f.read_bytes()


async def test_video_full_and_accept_ranges(sam, with_video):
    r = await sam.get("/lectures/lec_1/video")
    assert r.status_code == 200
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.content == with_video


async def test_video_range_requests(sam, with_video):
    r = await sam.get("/lectures/lec_1/video", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.content == with_video[10:20]
    assert r.headers["content-range"] == "bytes 10-19/1024"
    r = await sam.get("/lectures/lec_1/video", headers={"Range": "bytes=1000-"})
    assert r.status_code == 206 and r.content == with_video[1000:]
    r = await sam.get("/lectures/lec_1/video", headers={"Range": "bytes=-24"})
    assert r.status_code == 206 and r.content == with_video[-24:]


async def test_video_range_unsatisfiable(sam, with_video):
    r = await sam.get("/lectures/lec_1/video", headers={"Range": "bytes=5000-6000"})
    assert r.status_code == 416


async def test_video_missing_file_is_404(sam, db):
    await seed(db)
    assert (await sam.get("/lectures/lec_1/video")).status_code in (404, 409)
    assert (await sam.get("/lectures/nope/video")).status_code == 404
