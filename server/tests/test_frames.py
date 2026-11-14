from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.frames import SMALL_EDGE, parse_frame_times, sample_frames
from app.pipeline.interfaces import VideoCheckError
from tests.synthetic_media import make_video


def test_samples_one_frame_per_interval_with_exact_times(tmp_path: Path) -> None:
    video = make_video(tmp_path / "v.mp4", width=1280, height=720, duration_s=10, rate=25, audio=False)
    frames = sample_frames(video, tmp_path / "out", interval_s=3)
    assert [f.time_s for f in frames] == pytest.approx([0.0, 3.0, 6.0, 9.0])
    assert [f.index for f in frames] == [0, 1, 2, 3]
    for f in frames:
        with Image.open(f.path) as full, Image.open(f.small_path) as small:
            assert full.format == "JPEG" and full.size == (1280, 720)
            assert small.format == "JPEG" and small.size == (SMALL_EDGE, 432)


def test_fractional_interval_does_not_drift(tmp_path: Path) -> None:
    video = make_video(tmp_path / "v.mp4", width=320, height=240, duration_s=5, rate=10, audio=False)
    frames = sample_frames(video, tmp_path / "out", interval_s=1.5)
    assert [f.time_s for f in frames] == pytest.approx([0.0, 1.5, 3.0, 4.5])


def test_small_copy_never_upscales_and_keeps_portrait(tmp_path: Path) -> None:
    video = make_video(tmp_path / "v.mp4", width=360, height=1280, duration_s=1, audio=False)
    frames = sample_frames(video, tmp_path / "out", interval_s=5)
    assert len(frames) == 1
    with Image.open(frames[0].small_path) as small:
        assert small.size[1] == SMALL_EDGE and small.size[0] < SMALL_EDGE

    tiny = make_video(tmp_path / "tiny.mp4", width=320, height=240, duration_s=1, audio=False)
    (frame,) = sample_frames(tiny, tmp_path / "tiny_out", interval_s=5)
    with Image.open(frame.small_path) as small:
        assert small.size == (320, 240)


def test_rerun_replaces_old_frames(tmp_path: Path) -> None:
    video = make_video(tmp_path / "v.mp4", width=320, height=240, duration_s=6, audio=False)
    assert len(sample_frames(video, tmp_path / "out", interval_s=1)) == 6
    assert len(sample_frames(video, tmp_path / "out", interval_s=3)) == 2
    assert len(list((tmp_path / "out" / "frames").glob("*.jpg"))) == 2


def test_unreadable_video_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"nope" * 50)
    with pytest.raises(VideoCheckError):
        sample_frames(bad, tmp_path / "out", interval_s=3)


def test_parse_frame_times_ignores_other_lines() -> None:
    log = "\n".join(
        [
            "Input #0, mov,mp4, from 'v.mp4':",
            "[Parsed_showinfo_1 @ 0x1] n:   0 pts:      0 pts_time:0       duration:512",
            "[Parsed_showinfo_1 @ 0x1] n:   1 pts:  46080 pts_time:3.0    duration:512",
            "frame=    2 fps=0.0 q=2.0 size=N/A time=00:00:03.00",
        ]
    )
    assert parse_frame_times(log) == [0.0, 3.0]
