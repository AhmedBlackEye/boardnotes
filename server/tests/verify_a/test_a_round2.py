"""V2 round 2: written from the spec (interfaces, CLAUDE.md rules, task acceptance)."""

import asyncio
import io
import subprocess
import wave
from pathlib import Path

import pytest
from PIL import Image as PILImage

from app.config import settings
from app.contracts.ai import FrameGlance
from app.llm.fake import FakeLLM
from app.pipeline import video as video_mod
from app.pipeline.frames import sample_frames
from app.pipeline.interfaces import VideoCheckError
from app.pipeline.keyframes import GlancedFrame, choose_keyframes, glance_frames, select_keyframes
from app.pipeline.video import extract_audio, probe_video


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)  # noqa: S603, S607


def mk(path: Path, dur=6, size="640x360", extra=()):
    ff("-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration={dur}", "-f", "lavfi", "-i",
       f"sine=frequency=300:duration={dur}", "-pix_fmt", "yuv420p", *extra, str(path))
    return path


# ---- A-1 security / robustness ----
def test_hls_playlist_disguised_as_mp4_rejected(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    p = tmp_path / "lecture.mp4"
    p.write_text(f"#EXTM3U\n#EXTINF:1,\nfile:{secret}\n#EXT-X-ENDLIST\n")
    with pytest.raises(VideoCheckError):
        probe_video(p)
    with pytest.raises(VideoCheckError):
        extract_audio(p, tmp_path / "o")
    with pytest.raises(VideoCheckError):
        sample_frames(p, tmp_path / "o2", 3.0)


def test_concat_script_disguised_rejected_everywhere(tmp_path):
    good = mk(tmp_path / "good.mp4", dur=2)
    p = tmp_path / "x.mkv"
    p.write_text(f"ffconcat version 1.0\nfile '{good}'\n")
    for fn in (lambda: probe_video(p), lambda: extract_audio(p, tmp_path / "a"), lambda: sample_frames(p, tmp_path / "f", 1.0)):
        with pytest.raises(VideoCheckError):
            fn()


def test_symlink_to_real_video_ok_and_directory_rejected(tmp_path):
    real = mk(tmp_path / "r.mp4", dur=2)
    link = tmp_path / "link.mp4"
    link.symlink_to(real)
    assert probe_video(link).has_video
    with pytest.raises(VideoCheckError):
        probe_video(tmp_path)


def test_empty_file_rejected(tmp_path):
    p = tmp_path / "e.mp4"
    p.write_bytes(b"")
    with pytest.raises(VideoCheckError):
        probe_video(p)


def test_truncated_video_only_raises_check_error(tmp_path):
    real = mk(tmp_path / "r.mp4", dur=4)
    cut = tmp_path / "cut.mp4"
    cut.write_bytes(real.read_bytes()[:2000])
    with pytest.raises(VideoCheckError):
        probe_video(cut)


def test_duration_limit_enforced(tmp_path, monkeypatch):
    p = mk(tmp_path / "v.mp4", dur=4)
    monkeypatch.setattr(settings, "max_duration_s", 2.0)
    with pytest.raises(VideoCheckError):
        probe_video(p)


def test_rotated_phone_video_dimensions(tmp_path):
    p = mk(tmp_path / "r.mp4", dur=2, size="1280x720", extra=("-metadata:s:v", "rotate=90"))
    info = probe_video(p)
    assert (info.width, info.height) in {(720, 1280), (1280, 720)}
    if info.width == 720:
        assert info.warnings == []


def test_resolution_warning_boundaries(tmp_path):
    assert probe_video(mk(tmp_path / "a.mp4", dur=2, size="1280x720")).warnings == []
    assert probe_video(mk(tmp_path / "b.mp4", dur=2, size="640x360")).warnings != []


def test_probe_info_types_seconds(tmp_path):
    info = probe_video(mk(tmp_path / "a.mp4", dur=5))
    assert isinstance(info.duration_s, float)
    assert 4.5 < info.duration_s < 5.6
    assert info.has_audio and info.has_video


def test_audio_output_is_pcm16_mono_16k_and_duration(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=5)
    out = extract_audio(p, tmp_path / "deep" / "dir")
    assert out.exists() and out.suffix == ".wav"
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert abs(w.getnframes() / 16000 - 5) < 0.3


def test_error_messages_are_plain_language(tmp_path):
    p = tmp_path / "x.mp4"
    p.write_text("not video")
    with pytest.raises(VideoCheckError) as e:
        probe_video(p)
    msg = str(e.value)
    assert msg and "Traceback" not in msg and "ffprobe" not in msg and str(tmp_path) not in msg


def test_tool_invocations_use_safe_input(monkeypatch, tmp_path):
    calls = []
    real = video_mod.run_tool

    def spy(args, *a, **k):
        calls.append(list(args))
        return real(args, *a, **k)

    monkeypatch.setattr(video_mod, "run_tool", spy)
    p = mk(tmp_path / "a.mp4", dur=2)
    probe_video(p)
    extract_audio(p, tmp_path / "o")
    assert calls
    for c in calls:
        assert c[c.index("-protocol_whitelist") + 1] == "file"
        assert any(a.startswith("file:") for a in c)


# ---- A-2 ----
def test_frame_times_floats_seconds_monotonic_and_spacing(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=10)
    fr = sample_frames(p, tmp_path / "o", 3.0)
    ts = [f.time_s for f in fr]
    assert ts == sorted(ts) and all(isinstance(t, float) for t in ts)
    assert len(fr) in (3, 4) and ts[0] < 0.5
    for a, b in zip(ts, ts[1:], strict=False):
        assert 2.5 <= b - a <= 3.5
    assert [f.index for f in fr] == list(range(len(fr)))


def test_small_copies_le_768_and_full_res_kept(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=4, size="1920x1080")
    for f in sample_frames(p, tmp_path / "o", 3.0):
        with PILImage.open(f.small_path) as s:
            assert max(s.size) <= 768
        with PILImage.open(f.path) as full:
            assert full.size == (1920, 1080)
            assert full.format == "JPEG"


def test_zero_and_negative_interval_rejected(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=2)
    for bad in (0, -1):
        with pytest.raises((ValueError, VideoCheckError)):
            sample_frames(p, tmp_path / "o", bad)


def test_fractional_interval(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=4)
    assert 7 <= len(sample_frames(p, tmp_path / "o", 0.5)) <= 9


def test_max_frames_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "max_frames", 2)
    p = mk(tmp_path / "a.mp4", dur=10)
    assert len(sample_frames(p, tmp_path / "o", 1.0)) == 2


# ---- A-3 ----
class _F:
    def __init__(self, t):
        self.time_s = float(t)
        self.path = Path(f"/x/{t}.jpg")
        self.small_path = Path(f"/x/s{t}.jpg")
        self.index = int(t)


def G(t, lines, readable=0.9, board=True):
    return GlancedFrame(frame=_F(t), glance=FrameGlance(shows_board=board, readable=readable, lines=lines))  # pyright: ignore[reportArgumentType]


A, B, C = "x squared plus y squared equals r squared", "integral of sin x dx from zero to pi", "therefore the area is two units"


def test_every_new_line_gets_a_keyframe_covering_it():
    kfs = choose_keyframes([G(0, [A]), G(3, [A, B]), G(6, [A, B, C])])
    seen = {ln for k in kfs for ln in k.lines}
    assert {A, B, C} <= seen
    assert len(kfs) <= 3


def test_identical_frames_collapse_many():
    assert len(choose_keyframes([G(t, [A, B]) for t in range(0, 60, 3)])) == 1


def test_lecturer_blocks_board_then_returns_no_duplicate():
    assert len(choose_keyframes([G(0, [A, B]), G(3, [], readable=0.1), G(6, [A, B])])) == 1


def test_clearest_frame_wins_for_same_text():
    kfs = choose_keyframes([G(0, [A], readable=0.2), G(3, [A], readable=0.95), G(6, [A], readable=0.4)])
    assert [k.time_s for k in kfs] == [3.0]


def test_only_non_board_frames_gives_empty_and_empty_input():
    assert choose_keyframes([G(0, [A], board=False), G(3, [], board=False)]) == []
    assert choose_keyframes([]) == []


def test_keyframe_fields_come_from_the_chosen_frame():
    k = choose_keyframes([G(4, [A], readable=0.7)])[0]
    assert k.time_s == 4.0 and k.path == Path("/x/4.jpg") and k.lines == [A] and k.readable == 0.7


def test_keyframes_sorted_by_time():
    kfs = choose_keyframes([G(9, [C]), G(0, [A]), G(5, [B])])
    assert [k.time_s for k in kfs] == sorted(k.time_s for k in kfs)


def test_new_line_added_is_new_writing():
    kfs = choose_keyframes([G(0, ["the answer is 12345 metres"]), G(3, ["the answer is 12345 metres", "next, we derive force = mass times acceleration"])])
    assert any("force" in " ".join(k.lines) for k in kfs)


def test_empty_lines_and_whitespace_only_tolerated():
    assert len(choose_keyframes([G(0, ["", "   ", A]), G(3, [A])])) == 1


async def test_glance_requests_follow_rules(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=7)
    frames = sample_frames(p, tmp_path / "o", 3.0)
    llm = FakeLLM()
    out = await glance_frames(frames, llm)
    assert len(out) == len(frames) == len(llm.requests)
    for r in llm.requests:
        assert r.tier == "glance"
        assert r.task == "frame_glance"
        assert len(r.images) == 1
        assert max(PILImage.open(io.BytesIO(r.images[0].data)).size) <= 768
        assert "<data" not in r.instructions


async def test_glance_concurrency_is_bounded(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=30)
    frames = sample_frames(p, tmp_path / "o", 1.0)
    state = {"cur": 0, "max": 0}

    class Slow:
        usage = None

        async def structured(self, req, schema):
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
            await asyncio.sleep(0.01)
            state["cur"] -= 1
            return schema(shows_board=True, readable=0.5, lines=[req.task])

    res = await glance_frames(frames, Slow(), concurrency=3)  # type: ignore[arg-type]
    assert len(res) == len(frames) and state["max"] <= 3


async def test_glance_error_propagates(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=4)
    frames = sample_frames(p, tmp_path / "o", 3.0)

    class Boom:
        async def structured(self, req, schema):
            raise RuntimeError("model down")

    with pytest.raises(RuntimeError):
        await glance_frames(frames, Boom())  # type: ignore[arg-type]


async def test_select_keyframes_paths_exist_and_times_in_range(tmp_path):
    p = mk(tmp_path / "a.mp4", dur=9)
    kfs = await select_keyframes(p, tmp_path / "o", FakeLLM(), 3.0)
    assert kfs
    for k in kfs:
        assert k.path.exists() and 0 <= k.time_s <= 9.5 and isinstance(k.time_s, float)
        assert 0 <= k.readable <= 1


async def test_select_keyframes_on_bad_video_raises_check_error(tmp_path):
    p = tmp_path / "bad.mp4"
    p.write_text("nope")
    with pytest.raises(VideoCheckError):
        await select_keyframes(p, tmp_path / "o", FakeLLM(), 3.0)
