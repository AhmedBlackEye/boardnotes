import asyncio
from pathlib import Path

from app.contracts.ai import FrameGlance
from app.llm.client import LLMRequest, T
from app.llm.fake import FakeLLM
from app.pipeline.frames import SMALL_DIR, SampledFrame
from app.pipeline.interfaces import KeyframeSelector
from app.pipeline.keyframes import GLANCE_CONCURRENCY, GlancedFrame, choose_keyframes, normalise, select_keyframes
from tests.synthetic_media import make_video

_selector: KeyframeSelector = select_keyframes

NO_BOARD = FrameGlance(shows_board=False, readable=0.0, lines=[])


def board(*lines: str, readable: float = 0.9) -> FrameGlance:
    return FrameGlance(shows_board=True, readable=readable, lines=list(lines))


def glanced(*glances: FrameGlance, interval_s: float = 3.0) -> list[GlancedFrame]:
    out = []
    for i, g in enumerate(glances):
        frame = SampledFrame(index=i, time_s=i * interval_s, path=Path(f"full/{i}.jpg"), small_path=Path(f"small/{i}.jpg"))
        out.append(GlancedFrame(frame=frame, glance=g))
    return out


def times(frames: list[GlancedFrame]) -> list[float]:
    return [k.time_s for k in choose_keyframes(frames)]


class ScriptedGlanceLLM(FakeLLM):
    """Test-only fake: answers each frame_glance request with the scripted FrameGlance for that frame index.
    The frame is identified by its image bytes, matched against the small frames written to out_dir."""

    def __init__(self, out_dir: Path, script: list[FrameGlance]) -> None:
        super().__init__()
        self.out_dir, self.script = out_dir, script
        self.in_flight = self.max_in_flight = 0

    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        assert req.task == "frame_glance" and req.tier == "glance" and schema is FrameGlance
        assert req.untrusted == {} and len(req.images) == 1
        self.requests.append(req)
        self.usage.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        smalls = sorted((self.out_dir / SMALL_DIR).glob("frame_*.jpg"))
        index = next(i for i, p in enumerate(smalls) if p.read_bytes() == req.images[0].data)
        return schema.model_validate(self.script[index].model_dump())


def test_normalise_ignores_case_and_spacing() -> None:
    assert normalise("Solve 2X + y = 3") == normalise("solve 2x+y=3 ") == "solve2x+y=3"


def test_camera_move_with_same_writing_gives_one_keyframe() -> None:
    frames = glanced(
        board("Solve 2x + y = 3", "x - 2y = -1"),
        board("x - 2y = -1", "Solve 2x+y=3"),  # panned: order changes, spacing read differently
        board("solve 2x + y = 3", "x-2y=-1", readable=0.85),
        board("Solve 2x + y = 3", "x - 2y = -l"),  # one character misread
    )
    assert times(frames) == [0.0]


def test_pan_revealing_new_writing_and_cut_off_lines() -> None:
    frames = glanced(
        board("Row picture", "Solve 2x + y = 3", "x - 2y = -1, and fi"),  # last line cut off at the right edge
        board("Solve 2x + y = 3", "x - 2y = -1, and find out", "Column picture"),  # panned right
        board("x - 2y = -1, and find out", "Column picture"),
    )
    keyframes = choose_keyframes(frames)
    # Frame 0 is the only one with "Row picture"; frame 1 has the full line and the new "Column picture".
    assert [k.time_s for k in keyframes] == [0.0, 3.0]
    assert keyframes[1].path == Path("full/1.jpg")
    assert keyframes[1].lines == ["Solve 2x + y = 3", "x - 2y = -1, and find out", "Column picture"]
    assert keyframes[1].readable == 0.9


def test_occlusion_keeps_the_most_complete_frame() -> None:
    frames = glanced(
        board("Solve 2x + y = 3", "x - 2y ="),  # lecturer hides the end of line 2
        board("Solve 2x + y = 3", "x - 2y = -1, and find out"),
        board("Solve 2x", "x - 2y = -1, and find out"),  # lecturer hides the end of line 1
    )
    assert times(frames) == [3.0]


def test_lecturer_briefly_blocking_the_board_is_not_an_erase() -> None:
    frames = glanced(
        board("Solve 2x + y = 3", "x - 2y = -1", "x = 2y - 1"),
        board("x = 2y"),  # almost everything hidden
        board("Solve 2x + y = 3", "x - 2y = -1", "x = 2y - 1"),
    )
    assert times(frames) == [0.0]


def test_writing_in_progress_keeps_the_finished_line() -> None:
    frames = glanced(board("Solve"), board("Solve 2x + y"), board("Solve 2x + y = 3"))
    assert times(frames) == [6.0]


def test_new_line_added_supersedes_earlier_frame() -> None:
    frames = glanced(board("Solve 2x + y = 3"), board("Solve 2x + y = 3", "x - 2y = -1"))
    assert times(frames) == [3.0]


def test_blurrier_frame_loses_to_clearer_one() -> None:
    frames = glanced(board("Solve 2x + y = 3", readable=0.4), board("Solve 2x + y = 3", readable=0.95))
    assert times(frames) == [3.0]


def test_erase_keeps_last_frame_before_the_drop() -> None:
    frames = glanced(
        board("Gaussian elimination", "pivot = a11", "R2 <- R2 - 3 R1", readable=0.95),
        board("Gaussian elimination", "pivot = a11", "R2 <- R2 - 3 R1", readable=0.6),  # last view before erasing
        board(readable=0.9),  # empty board
        board("Determinants", "det(A) = ad - bc"),
        board("Determinants", "det(A) = ad - bc"),
    )
    assert times(frames) == [0.0, 3.0, 9.0]


def test_no_board_frames_are_skipped() -> None:
    assert times(glanced(NO_BOARD, NO_BOARD)) == []
    frames = glanced(
        NO_BOARD,
        board("Solve 2x + y = 3", "x - 2y = -1"),
        FrameGlance(shows_board=False, readable=0.0, lines=["Slide title"]),  # ignored even if text is reported
        NO_BOARD,  # camera on the lecturer: not an erase
        board("Solve 2x + y = 3", "x - 2y = -1"),
    )
    assert times(frames) == [3.0]


def test_noise_lines_are_ignored() -> None:
    assert times(glanced(board("a", " ", ""), board("Solve 2x + y = 3"))) == [3.0]


async def test_select_keyframes_end_to_end(tmp_path: Path) -> None:
    video = make_video(tmp_path / "v.mp4", width=640, height=360, duration_s=10, audio=False)
    out_dir = tmp_path / "work"
    script = [
        NO_BOARD,  # 0 s
        board("Solve 2x + y = 3", "x - 2y ="),  # 1 s: partly hidden
        board("Solve 2x + y = 3", "x - 2y = -1"),  # 2 s
        board("x - 2y = -1", "Solve 2x+y=3"),  # 3 s: camera moved
        board("Solve 2x + y = 3", "x - 2y = -1", "x = 2y - 1"),  # 4 s: new line, the most complete view
        board("Solve 2x + y = 3", "x - 2y = -1", "x = 2y - 1", readable=0.5),  # 5 s: last before erase
        board(),  # 6 s: erased
        NO_BOARD,  # 7 s
        board("Column picture"),  # 8 s
        board("Column picture", "b = x a1 + y a2"),  # 9 s
    ]
    llm = ScriptedGlanceLLM(out_dir, script)
    keyframes = await select_keyframes(video, out_dir, llm, interval_s=1.0)

    assert [k.time_s for k in keyframes] == [4.0, 5.0, 9.0]
    assert all(k.path.exists() and k.path.parent == out_dir / "frames" for k in keyframes)
    assert keyframes[0].lines == ["Solve 2x + y = 3", "x - 2y = -1", "x = 2y - 1"]
    assert llm.usage.calls == 10
    assert 1 < llm.max_in_flight <= GLANCE_CONCURRENCY


async def test_select_keyframes_with_default_fixture(tmp_path: Path, fake_llm: FakeLLM) -> None:
    video = make_video(tmp_path / "v.mp4", width=320, height=240, duration_s=6, audio=False)
    keyframes = await select_keyframes(video, tmp_path / "work", fake_llm, interval_s=3.0)
    assert [k.time_s for k in keyframes] == [0.0]  # same board text in every frame
    assert all(r.task == "frame_glance" and r.images for r in fake_llm.requests)
