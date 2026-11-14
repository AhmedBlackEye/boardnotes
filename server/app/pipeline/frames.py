"""Frame sampling for keyframe selection: one frame every `interval_s` seconds.

ffmpeg's `select` filter keeps the first decoded frame at or after each multiple of `interval_s` (so times don't
drift on long videos), and `showinfo` reports each kept frame's exact timestamp. Frames are saved as full-resolution
JPEGs for the accurate board read, plus small copies (long edge <= SMALL_EDGE px) for the cheap glance pass.
"""

import re
import subprocess  # noqa: S404 - fixed argument lists, never a shell
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import settings

from .interfaces import VideoCheckError
from .video import run_tool, safe_input

SMALL_EDGE = 768
FULL_DIR = "frames"
SMALL_DIR = "frames_small"
_PTS_TIME = re.compile(r"\bpts_time:\s*(-?[0-9.]+)")


@dataclass(frozen=True)
class SampledFrame:
    index: int  # position in the sample, 0-based
    time_s: float  # exact timestamp of the frame in the video
    path: Path  # full-resolution JPEG
    small_path: Path  # long edge <= SMALL_EDGE px


def select_filter(interval_s: float) -> str:
    """ffmpeg filter that keeps the first frame in each `interval_s` window and logs its timestamp."""
    i = f"{interval_s:g}"
    return f"select='isnan(prev_selected_t)+gt(floor(t/{i}),floor(prev_selected_t/{i}))',showinfo"


def parse_frame_times(ffmpeg_log: str) -> list[float]:
    """Timestamps of the frames `showinfo` reported, in output order."""
    return [float(m.group(1)) for line in ffmpeg_log.splitlines() if "showinfo" in line for m in [_PTS_TIME.search(line)] if m]


def make_small(src: Path, dst: Path, max_edge: int = SMALL_EDGE) -> None:
    """Save a copy of `src` whose long edge is at most `max_edge` (never upscales)."""
    try:
        with Image.open(src) as img:
            small = img.convert("RGB")
            small.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            small.save(dst, "JPEG", quality=85)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as e:
        raise VideoCheckError("We couldn't read the picture in this video. Please check the file plays correctly.") from e


def sample_frames(video: Path, out_dir: Path, interval_s: float, small_edge: int = SMALL_EDGE) -> list[SampledFrame]:
    """Extract one frame every `interval_s` seconds into out_dir/frames and out_dir/frames_small."""
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    full_dir, small_dir = out_dir / FULL_DIR, out_dir / SMALL_DIR
    full_dir.mkdir(parents=True, exist_ok=True)
    small_dir.mkdir(parents=True, exist_ok=True)
    for old in [*full_dir.glob("frame_*.jpg"), *small_dir.glob("frame_*.jpg")]:
        old.unlink()  # a retried job must not mix in frames from an earlier run

    args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-y", *safe_input(video), "-map", "0:v:0", "-an"]
    args += ["-t", str(settings.max_duration_s)]  # enforce the limit while decoding, not only from metadata
    args += [
        "-vf",
        select_filter(interval_s),
        "-fps_mode",
        "vfr",
        "-frames:v",
        str(settings.max_frames),
        "-q:v",
        "2",
        str(full_dir / "frame_%05d.jpg"),
    ]
    try:
        result = run_tool(args)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise VideoCheckError("We couldn't read the picture in this video. Please check the file plays correctly.") from e

    times = parse_frame_times(result.stderr)
    paths = sorted(full_dir.glob("frame_*.jpg"), key=lambda p: int(p.stem.removeprefix("frame_")))
    if len(times) != len(paths):
        raise RuntimeError(f"ffmpeg wrote {len(paths)} frames but reported {len(times)} timestamps")

    frames: list[SampledFrame] = []
    for index, (time_s, path) in enumerate(zip(times, paths, strict=True)):
        small_path = small_dir / path.name
        make_small(path, small_path, small_edge)
        frames.append(SampledFrame(index=index, time_s=max(time_s, 0.0), path=path, small_path=small_path))
    return frames
