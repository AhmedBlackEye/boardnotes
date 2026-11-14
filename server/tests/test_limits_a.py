"""Cost and disk limits on uploaded videos (V3 findings)."""

import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.pipeline.frames import sample_frames
from app.pipeline.interfaces import VideoCheckError
from app.pipeline.video import probe_video


def _make(path: Path, dur: int = 6) -> Path:
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=duration={dur}:size=320x240:rate=5"]
    args += ["-f", "lavfi", "-i", f"sine=duration={dur}", "-shortest", str(path)]
    subprocess.run(args, check=True)  # noqa: S603, S607
    return path


def test_rejects_too_long(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = _make(tmp_path / "v.mp4")
    monkeypatch.setattr(settings, "max_duration_s", 2.0)
    with pytest.raises(VideoCheckError):
        probe_video(video)


def test_frame_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = _make(tmp_path / "v.mp4")
    monkeypatch.setattr(settings, "max_frames", 2)
    frames = sample_frames(video, tmp_path / "out", 1.0)
    assert len(frames) == 2
