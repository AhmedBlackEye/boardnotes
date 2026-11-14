import json
import subprocess  # noqa: S404
from pathlib import Path

import pytest

from app.pipeline.interfaces import AudioExtractor, Probe, VideoCheckError
from app.pipeline.video import LOW_RES, extract_audio, probe_video
from tests.synthetic_media import make_audio_only, make_video

# Static check that the implementations match the stage protocols.
_probe: Probe = probe_video
_extract: AudioExtractor = extract_audio


def test_probe_good_video(tmp_path: Path) -> None:
    info = probe_video(make_video(tmp_path / "v.mp4", width=1280, height=720, duration_s=3))
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (1280, 720)
    assert info.duration_s == pytest.approx(3.0, abs=0.15)
    assert info.warnings == []


def test_probe_warns_below_720p(tmp_path: Path) -> None:
    info = probe_video(make_video(tmp_path / "v.mp4", width=640, height=360, duration_s=1))
    assert info.warnings == [LOW_RES]


def test_probe_rejects_video_without_sound(tmp_path: Path) -> None:
    with pytest.raises(VideoCheckError, match="no sound"):
        probe_video(make_video(tmp_path / "v.mp4", duration_s=1, audio=False))


def test_probe_rejects_audio_only(tmp_path: Path) -> None:
    with pytest.raises(VideoCheckError, match="no picture"):
        probe_video(make_audio_only(tmp_path / "a.m4a"))


@pytest.mark.parametrize("content", [b"", b"this is not a video at all" * 100])
def test_probe_rejects_unreadable_file(tmp_path: Path, content: bytes) -> None:
    bad = tmp_path / "lecture.mp4"
    bad.write_bytes(content)
    with pytest.raises(VideoCheckError, match="couldn't read"):
        probe_video(bad)


def test_probe_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(VideoCheckError):
        probe_video(tmp_path / "missing.mp4")


def test_extract_audio_is_mono_16k_wav(tmp_path: Path) -> None:
    video = make_video(tmp_path / "v.mp4", duration_s=2)
    out = extract_audio(video, tmp_path / "out")
    assert out.parent == tmp_path / "out" and out.suffix == ".wav"
    probe = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(out)],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(probe.stdout)
    stream = data["streams"][0]
    assert stream["codec_name"] == "pcm_s16le"
    assert stream["channels"] == 1
    assert stream["sample_rate"] == "16000"
    assert float(data["format"]["duration"]) == pytest.approx(2.0, abs=0.15)


def test_extract_audio_without_sound_raises(tmp_path: Path) -> None:
    video = make_video(tmp_path / "v.mp4", duration_s=1, audio=False)
    with pytest.raises(VideoCheckError):
        extract_audio(video, tmp_path / "out")


def test_probe_rejects_hls_playlist_renamed_to_mp4(tmp_path: Path) -> None:
    (tmp_path / "seg.ts").write_bytes(b"x")
    evil = tmp_path / "lecture.mp4"
    evil.write_text("#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:1,\nseg.ts\n#EXT-X-ENDLIST\n")
    with pytest.raises(VideoCheckError):
        probe_video(evil)


def test_probe_rejects_concat_file_renamed_to_mp4(tmp_path: Path) -> None:
    real = make_video(tmp_path / "real.mp4", duration_s=1)
    evil = tmp_path / "lecture.mp4"
    evil.write_text(f"ffconcat version 1.0\nfile '{real}'\n")
    with pytest.raises(VideoCheckError):
        probe_video(evil)


def test_extract_audio_rejects_concat_file(tmp_path: Path) -> None:
    real = make_video(tmp_path / "real.mp4", duration_s=1)
    evil = tmp_path / "lecture.mp4"
    evil.write_text(f"ffconcat version 1.0\nfile '{real}'\n")
    with pytest.raises(VideoCheckError):
        extract_audio(evil, tmp_path / "out")


def test_probe_accepts_dash_leading_filename(tmp_path: Path) -> None:
    assert probe_video(make_video(tmp_path / "-v.mp4", duration_s=1)).has_video
