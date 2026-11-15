"""The accuracy scorer itself must be right, or the measurements mean nothing."""

import importlib.util
import json
from pathlib import Path

from app.contracts.ai import BoardRead, BoardReadBlock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("score_board", ROOT / "eval" / "score_board.py")
assert spec and spec.loader
score_board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score_board)

LABEL = {
    "lines": ["Solve 2x + y = 3, x − 2y = −1, and find out", "x = 2y − 1"],
    "partial": ["⇒ 5y − 2 = 3 ⇒ …"],
    "latex": [r"x = 2y - 1"],
    "diagrams": ["Coordinate axes"],
}


def block(text: str, latex: str | None = None, kind: str = "text", conf: float = 0.9) -> BoardReadBlock:
    return BoardReadBlock(type=kind, text=text, latex=latex, bbox=[0, 0, 1, 1], confidence=conf)  # type: ignore[arg-type]


def test_perfect_read_scores_full_marks() -> None:
    read = BoardRead(
        frame_quality="good",
        blocks=[
            block("Solve 2x + y = 3, x - 2y = -1, and find out"),
            block("x = 2y - 1", r"x = 2y - 1", "math"),
            block("axes", kind="diagram"),
        ],
    )
    s = score_board.summarise([score_board.score_frame("01", LABEL, read)])
    assert s["coverage"] == 1.0
    assert s["text_cer"] == 0.0
    assert s["formula_exact"] == 1.0
    assert s["diagram_recall"] == 1.0
    assert s["invented"] == 0


def test_missing_lines_wrong_formula_and_invented_text_are_penalised() -> None:
    read = BoardRead(frame_quality="good", blocks=[block("x = 2y + 1", r"x = 2y + 1", "math", 0.9), block("Photosynthesis", conf=0.8)])
    s = score_board.summarise([score_board.score_frame("01", LABEL, read)])
    assert s["coverage"] < 1.0
    assert s["formula_exact"] == 0.0
    assert s["diagram_recall"] == 0.0
    assert s["invented"] >= 1


def test_labels_are_well_formed() -> None:
    frames = sorted((ROOT / "fixtures" / "frames").glob("[0-9][0-9].json"))
    assert len(frames) == 15
    for f in frames:
        label = json.loads(f.read_text())
        assert {"time_s", "lines", "partial", "latex", "diagrams", "status"} <= label.keys(), f
        assert (f.parent / f"{f.stem}.jpg").exists()
