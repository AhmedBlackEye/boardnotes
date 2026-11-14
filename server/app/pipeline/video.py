"""Video check and audio extraction (stage 1). Uses the ffprobe / ffmpeg command-line tools.

Every failure a lecturer can fix (wrong file, no picture, no sound) raises `VideoCheckError` with a message
written for them; it is shown in the upload screen as is.
"""

import json
import subprocess  # noqa: S404 - fixed argument lists, never a shell
from pathlib import Path
from typing import Any

from .interfaces import VideoCheckError, VideoInfo

MIN_GOOD_HEIGHT = 720
FFMPEG_TIMEOUT_S = 60 * 60  # a 2 h lecture is decoded once per pass; generous upper bound

UNREADABLE = "We couldn't read this file as a video. Please upload a lecture recording such as an MP4 or MOV file."
NO_PICTURE = "This file has no picture. Please upload a video recording of the lecture, not just the audio."
NO_SOUND = "This video has no sound. BoardNotes needs the lecturer's voice, so please upload a recording with audio."
LOW_RES = "Resolution below 720p: board text may be hard to read"


def run_tool(args: list[str], timeout_s: float = FFMPEG_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    """Run ffmpeg/ffprobe with a fixed argument list. Raises CalledProcessError on a non-zero exit."""
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout_s)  # noqa: S603


def _probe_json(video: Path) -> dict[str, Any]:
    if not video.is_file():
        raise VideoCheckError(UNREADABLE)
    try:
        result = run_tool(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)], 120)
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        raise VideoCheckError(UNREADABLE) from e
    if not isinstance(data, dict) or "format" not in data:
        raise VideoCheckError(UNREADABLE)
    return data


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rotated(stream: dict[str, Any]) -> bool:
    """True for phone videos stored sideways (rotation 90/270), whose displayed width and height are swapped."""
    rotation = _float(stream.get("tags", {}).get("rotate"))
    for side in stream.get("side_data_list", []):
        rotation = _float(side.get("rotation")) if "rotation" in side else rotation
    return rotation is not None and round(abs(rotation)) % 180 == 90


def probe_video(video: Path) -> VideoInfo:
    """Check that `video` is a readable recording with picture and sound. Matches the `Probe` protocol."""
    data = _probe_json(video)
    streams: list[dict[str, Any]] = data.get("streams", [])
    # Cover art in audio files shows up as a one-frame video stream; it is not a picture of the lecture.
    pictures = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    sounds = [s for s in streams if s.get("codec_type") == "audio"]
    if not pictures and not sounds:
        raise VideoCheckError(UNREADABLE)
    if not pictures:
        raise VideoCheckError(NO_PICTURE)
    if not sounds:
        raise VideoCheckError(NO_SOUND)

    picture = pictures[0]
    width, height = int(picture.get("width") or 0), int(picture.get("height") or 0)
    if width <= 0 or height <= 0:
        raise VideoCheckError(UNREADABLE)
    if _rotated(picture):
        width, height = height, width

    duration = _float(data["format"].get("duration")) or _float(picture.get("duration"))
    if duration is None or duration <= 0:
        raise VideoCheckError(UNREADABLE)

    warnings = [LOW_RES] if min(width, height) < MIN_GOOD_HEIGHT else []
    return VideoInfo(duration_s=duration, width=width, height=height, has_video=True, has_audio=True, warnings=warnings)


def extract_audio(video: Path, out_dir: Path) -> Path:
    """Write the soundtrack as mono 16 kHz 16-bit WAV (what speech-to-text expects). Matches `AudioExtractor`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "audio.wav"
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video), "-map", "0:a:0", "-vn"]
    args += ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)]
    try:
        run_tool(args)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise VideoCheckError("We couldn't extract the sound from this video. Please check the file plays with audio.") from e
    return out
