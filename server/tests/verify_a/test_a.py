"""V2 independent tests for workstream A (video, frames, keyframes), written from the spec."""

import subprocess
import wave
from pathlib import Path

import pytest
from PIL import Image

from app.contracts.ai import FrameGlance
from app.llm.client import LLMRequest
from app.pipeline.frames import sample_frames
from app.pipeline.interfaces import Keyframe, VideoCheckError
from app.pipeline.keyframes import GlancedFrame, choose_keyframes, glance_frames, select_keyframes
from app.pipeline.video import extract_audio, probe_video


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)  # noqa: S603, S607


def make_video(path: Path, dur=10, size="1280x720", audio=True, video=True):
    ins = []
    if video:
        ins += ["-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration={dur}"]
    if audio:
        ins += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={dur}"]
    if video:
        ff(*ins, "-pix_fmt", "yuv420p", str(path))
    else:
        ff(*ins, str(path))
    return path


@pytest.fixture(scope="module")
def vid(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("v") / "ok.mp4", dur=10)


# ---------------- A-1 ----------------
def test_probe_ok(vid):
    info = probe_video(vid)
    assert info.has_video and info.has_audio
    assert info.duration_s == pytest.approx(10, abs=0.3)
    assert (info.width, info.height) == (1280, 720)
    assert info.warnings == []
    assert isinstance(info.duration_s, float)


def test_probe_low_res_warns(tmp_path):
    p = make_video(tmp_path / "lo.mp4", dur=2, size="640x360")
    info = probe_video(p)
    assert any("720p" in w for w in info.warnings)


def test_probe_no_audio(tmp_path):
    p = make_video(tmp_path / "na.mp4", dur=2, audio=False)
    with pytest.raises(VideoCheckError) as e:
        probe_video(p)
    assert "sound" in str(e.value).lower() or "audio" in str(e.value).lower()


def test_probe_audio_only(tmp_path):
    p = make_video(tmp_path / "a.m4a", dur=2, video=False)
    with pytest.raises(VideoCheckError) as e:
        probe_video(p)
    assert "picture" in str(e.value).lower() or "video" in str(e.value).lower()


def test_probe_garbage_and_missing(tmp_path):
    g = tmp_path / "g.mp4"
    g.write_bytes(b"not a video at all" * 100)
    with pytest.raises(VideoCheckError):
        probe_video(g)
    with pytest.raises(VideoCheckError):
        probe_video(tmp_path / "missing.mp4")
    e = tmp_path / "e.mp4"
    e.write_bytes(b"")
    with pytest.raises(VideoCheckError):
        probe_video(e)


def test_probe_rejects_playlist_and_concat(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("hello")
    playlist = tmp_path / "evil.m3u8"
    playlist.write_text(f"#EXTM3U\n#EXTINF:1,\nfile:{secret}\n")
    with pytest.raises(VideoCheckError):
        probe_video(playlist)
    concat = tmp_path / "list.txt"
    concat.write_text(f"ffconcat version 1.0\nfile '{secret}'\n")
    with pytest.raises(VideoCheckError):
        probe_video(concat)


@pytest.mark.parametrize("name", ["http:x.mp4", "my video (1) 'q'.mp4", "-weird.mp4"])
def test_odd_filenames(tmp_path, name):
    p = tmp_path / name
    make_video(p, dur=2)
    assert probe_video(p).has_video
    out = extract_audio(p, tmp_path / "out")
    assert out.exists()


def test_extract_audio_mono_16k(vid, tmp_path):
    out = extract_audio(vid, tmp_path / "audio")
    assert out.suffix == ".wav" and out.exists()
    with wave.open(str(out)) as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 16000
        assert w.getnframes() / 16000 == pytest.approx(10, abs=0.3)


def test_extract_audio_stereo_downmix(tmp_path):
    p = tmp_path / "st.mp4"
    ff(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=1280x720:rate=10:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=duration=2:sample_rate=48000",
        "-ac",
        "2",
        "-pix_fmt",
        "yuv420p",
        str(p),
    )
    out = extract_audio(p, tmp_path / "o")
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 16000)


def test_extract_audio_bad_file_raises_check_error(tmp_path):
    g = tmp_path / "g.mp4"
    g.write_bytes(b"junk" * 50)
    with pytest.raises(VideoCheckError):
        extract_audio(g, tmp_path / "o")


# ---------------- A-2 ----------------
def test_sample_count_and_timestamps(vid, tmp_path):
    frames = sample_frames(vid, tmp_path, 3.0)
    times_ = [f.time_s for f in frames]
    assert len(frames) == 4  # 0,3,6,9 for a 10 s video
    for t, expect in zip(times_, [0, 3, 6, 9], strict=True):
        assert t == pytest.approx(expect, abs=0.25)
    assert times_ == sorted(times_)
    for f in frames:
        assert f.path.exists() and f.small_path.exists()
        with Image.open(f.path) as im:
            assert im.size == (1280, 720)
            assert im.format == "JPEG"
        with Image.open(f.small_path) as im:
            assert max(im.size) <= 768


def test_sample_small_never_upscales_and_portrait(tmp_path):
    p = make_video(tmp_path / "small.mp4", dur=4, size="320x240")
    fr = sample_frames(p, tmp_path / "o", 3.0)
    with Image.open(fr[0].small_path) as im:
        assert im.size == (320, 240)
    p2 = make_video(tmp_path / "port.mp4", dur=4, size="720x1280")
    fr = sample_frames(p2, tmp_path / "o2", 3.0)
    with Image.open(fr[0].small_path) as im:
        assert max(im.size) <= 768


def test_sample_interval_other_and_invalid(vid, tmp_path):
    fr = sample_frames(vid, tmp_path, 1.5)
    assert len(fr) in (6, 7)
    with pytest.raises(ValueError):
        sample_frames(vid, tmp_path, 0)
    with pytest.raises(ValueError):
        sample_frames(vid, tmp_path, -3)


def test_sample_rerun_does_not_mix(vid, tmp_path):
    sample_frames(vid, tmp_path, 1.0)
    fr = sample_frames(vid, tmp_path, 5.0)
    assert len(fr) == 2
    assert len(list((tmp_path / "frames").glob("*.jpg"))) == 2
    assert len(list((tmp_path / "frames_small").glob("*.jpg"))) == 2


def test_sample_shorter_than_interval(tmp_path):
    p = make_video(tmp_path / "s.mp4", dur=1)
    fr = sample_frames(p, tmp_path / "o", 3.0)
    assert len(fr) == 1 and fr[0].time_s < 0.5


def test_sample_rejects_non_video(tmp_path):
    g = tmp_path / "g.mp4"
    g.write_bytes(b"junk" * 100)
    with pytest.raises(VideoCheckError):
        sample_frames(g, tmp_path / "o", 3.0)


# ---------------- A-3 ----------------
class _F:
    def __init__(self, t):
        self.time_s = float(t)
        self.path = Path(f"/x/{t}.jpg")
        self.small_path = Path(f"/x/s{t}.jpg")
        self.index = int(t)


def G(t, lines, readable=0.9, board=True):
    return GlancedFrame(frame=_F(t), glance=FrameGlance(shows_board=board, readable=readable, lines=lines))  # pyright: ignore[reportArgumentType]


def times(kfs):
    return [k.time_s for k in kfs]


def test_empty_and_no_board():
    assert choose_keyframes([]) == []
    assert choose_keyframes([G(0, [], 0, False), G(3, ["x = 1 + 2"], 0.9, False)]) == []


def test_static_board_one_keyframe():
    fs = [G(t, ["2x + y = 3", "x - y = 0"]) for t in range(0, 30, 3)]
    assert len(choose_keyframes(fs)) == 1


def test_new_writing_adds_keyframe_and_returns_keyframe_objects():
    fs = [G(0, ["2x + y = 3"]), G(3, ["2x + y = 3"]), G(6, ["2x + y = 3", "x - y = 0"]), G(9, ["2x + y = 3", "x - y = 0"])]
    ks = choose_keyframes(fs)
    assert all(isinstance(k, Keyframe) for k in ks)
    assert times(ks) == sorted(times(ks))
    assert len(ks) <= 2
    assert any(len(k.lines) == 2 for k in ks)


def test_keeps_clearest_frame_per_writing():
    line = ["integral of sin x dx = -cos x"]
    fs = [G(0, line, 0.3), G(3, line, 0.95), G(6, line, 0.4)]
    assert times(choose_keyframes(fs)) == [3]


def test_occlusion_partial_text_prefers_complete():
    fs = [G(0, ["the derivative of x"]), G(3, ["the derivative of x squared is 2x"]), G(6, ["squared is 2x"])]
    assert times(choose_keyframes(fs)) == [3]


def test_camera_pan_cut_off_line_not_new_writing():
    fs = [G(0, ["a plus b equals c over two"]), G(3, ["plus b equals c over two"]), G(6, ["a plus b equals c over"])]
    assert len(choose_keyframes(fs)) == 1


def test_case_whitespace_insensitive():
    fs = [G(0, ["2x + y = 3"]), G(3, ["2X+Y=3"]), G(6, ["2x  +  y  =  3"])]
    assert len(choose_keyframes(fs)) == 1


def test_non_board_frames_in_between_ignored():
    fs = [G(0, ["2x + y = 3"]), G(3, [], 0, False), G(6, ["2x + y = 3"])]
    ks = choose_keyframes(fs)
    assert len(ks) == 1 and times(ks)[0] in (0, 6)


def test_erase_keeps_last_full_view():
    full = ["first long line of writing here", "second long line of writing here", "third long line of writing"]
    fs = [G(0, full[:1]), G(3, full[:2]), G(6, full), G(9, full), G(12, []), G(15, ["entirely new topic on the board now"])]
    ks = choose_keyframes(fs)
    assert any(len(k.lines) == 3 for k in ks), "fullest view before erase must be kept"
    assert any("new topic" in " ".join(k.lines) for k in ks)


def test_unsorted_input_deterministic():
    fs = [G(6, ["b b b b b"]), G(0, ["a a a a a"]), G(3, ["a a a a a"])]
    a = choose_keyframes(fs)
    b = choose_keyframes(list(reversed(fs)))
    assert times(a) == times(b) == sorted(times(a))


def test_noise_lines_ignored():
    fs = [G(0, ["2x + y = 3"]), G(3, ["2x + y = 3", "."]), G(6, ["2x + y = 3", "~"])]
    assert len(choose_keyframes(fs)) == 1


@pytest.mark.asyncio
async def test_glance_frames_uses_fake_llm_tier(vid, tmp_path):
    from app.llm.fake import FakeLLM

    llm = FakeLLM()
    frames = sample_frames(vid, tmp_path, 3.0)
    gl = await glance_frames(frames, llm)
    assert len(gl) == len(frames)
    assert all(isinstance(g, FrameGlance) for g in gl)
    assert len(llm.requests) == len(frames)
    for r in llm.requests:
        assert isinstance(r, LLMRequest)
        assert r.task == "frame_glance" and r.tier == "glance"
        assert len(r.images) == 1
        assert len({q.instructions for q in llm.requests}) == 1  # constant, trusted text only


@pytest.mark.asyncio
async def test_select_keyframes_end_to_end_fake(vid, tmp_path):
    from app.llm.fake import FakeLLM

    llm = FakeLLM()
    ks = await select_keyframes(vid, tmp_path, llm, 3.0)
    assert all(isinstance(k, Keyframe) for k in ks)
    assert all(k.path.exists() for k in ks)
    assert times(ks) == sorted(times(ks))
    assert len(llm.requests) == 4
    assert all(isinstance(k.time_s, float) for k in ks)
