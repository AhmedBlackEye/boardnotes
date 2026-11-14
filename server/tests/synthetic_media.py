"""Tiny synthetic media files made with ffmpeg's lavfi sources, so video tests need no fixtures on disk."""

import subprocess  # noqa: S404 - fixed argument lists, never a shell
from pathlib import Path


def make_video(path: Path, *, width: int = 1280, height: int = 720, duration_s: float = 4.0, audio: bool = True, rate: int = 25) -> Path:
    """testsrc2 picture with a drawn line of text, plus (optionally) a 440 Hz sine soundtrack."""
    picture = f"testsrc2=size={width}x{height}:rate={rate}:duration={duration_s:g},drawtext=text='x = 2y - 1':fontsize=32:x=20:y=20"
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", picture]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={duration_s:g}", "-c:a", "aac", "-ac", "2"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(args, check=True, capture_output=True)  # noqa: S603
    return path


def make_audio_only(path: Path, duration_s: float = 2.0) -> Path:
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_s:g}", str(path)]
    subprocess.run(args, check=True, capture_output=True)  # noqa: S603
    return path
