"""Files on disk: where each lecture's files live, and board snapshot crops.

Every path is built from ids we generated and checked to stay inside settings.data_dir; user-supplied
filenames never reach the filesystem.
"""

from pathlib import Path

from PIL import Image

SNAPSHOT_PAD = 0.03  # extra margin around the block, as a fraction of the frame


def lecture_dir(data_dir: Path, lecture_id: str) -> Path:
    return data_dir / "lectures" / lecture_id


def inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def crop_box(bbox: list[float], width: int, height: int, pad: float = SNAPSHOT_PAD) -> tuple[int, int, int, int]:
    """Pixel box for a normalised [x0, y0, x1, y1] bbox, padded and clamped to the frame. Never empty."""
    x0, y0, x1, y1 = (min(max(v, 0.0), 1.0) for v in bbox)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    left = max(0, int((x0 - pad) * width))
    top = max(0, int((y0 - pad) * height))
    right = min(width, max(left + 1, round((x1 + pad) * width)))
    bottom = min(height, max(top + 1, round((y1 + pad) * height)))
    return left, top, right, bottom


def grab_frame(video: Path, time_s: float) -> Image.Image | None:
    """Decode one frame from the video (used when the keyframe image is no longer on disk)."""
    import cv2

    cap = cv2.VideoCapture(str(video))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, time_s * 1000)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        return None
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def make_snapshot(out: Path, bbox: list[float], frame_path: Path | None, video_path: Path | None, time_s: float) -> bool:
    """Write the crop of the block to `out` (JPEG). Returns False if no source image is available. Blocking."""
    image: Image.Image | None = None
    if frame_path is not None and frame_path.is_file():
        image = Image.open(frame_path)
    elif video_path is not None and video_path.is_file():
        image = grab_frame(video_path, time_s)
    if image is None:
        return False
    with image:
        crop = image.convert("RGB").crop(crop_box(bbox, image.width, image.height))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    crop.save(tmp, "JPEG", quality=88)
    tmp.replace(out)
    return True
