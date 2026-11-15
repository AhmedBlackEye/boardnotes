from pathlib import Path

from app.contracts.ai import BoardRead, BoardReadBlock
from app.contracts.enums import BlockType
from app.pipeline.board import merge_blocks, normalise
from app.pipeline.interfaces import FrameReading, Keyframe


def blk(text: str, latex: str | None = None, conf: float = 0.9, bbox: tuple[float, ...] = (0.1, 0.1, 0.5, 0.2)) -> BoardReadBlock:
    return BoardReadBlock(type=BlockType.MATH if latex else BlockType.TEXT, text=text, latex=latex, bbox=list(bbox), confidence=conf)


def frame(t: float, *blocks: BoardReadBlock) -> FrameReading:
    kf = Keyframe(time_s=t, path=Path(f"/frames/{t}.jpg"), lines=[], readable=0.9)
    return FrameReading(keyframe=kf, read=BoardRead(blocks=list(blocks), frame_quality="good"))


def test_normalise_ignores_spacing_and_latex_sizing() -> None:
    assert normalise(r"\left( x + y \right) = 3") == normalise("(x+y)=3")
    assert normalise("x − 2y") == normalise("x - 2y")


def test_camera_move_duplicates_become_one_block() -> None:
    a = blk("x = 2y - 1", "x = 2y - 1", conf=0.8, bbox=(0.1, 0.4, 0.3, 0.5))
    b = blk("x = 2y - 1", "x=2y-1", conf=0.95, bbox=(0.5, 0.4, 0.7, 0.5))  # panned: same writing, new position
    c = blk("x = 2y -1", "x = 2y - 1", conf=0.85, bbox=(0.0, 0.3, 0.2, 0.4))
    out = merge_blocks([frame(3, a), frame(6, b), frame(9, c)])
    assert len(out) == 1
    assert out[0].first_seen_s == 3
    assert out[0].best_frame_s == 6
    assert out[0].confidence == 0.97  # best reading 0.95, plus agreement across frames
    assert out[0].bbox == [0.5, 0.4, 0.7, 0.5]


def test_fuller_reading_replaces_partial_even_if_less_confident() -> None:
    cut = blk("2x + y = 3", r"2x + y = 3", conf=0.97)  # bottom line cut off by the frame
    full = blk("2x + y = 3, x - 2y = -1", r"\begin{cases} 2x + y = 3 \\ x - 2y = -1 \end{cases}", conf=0.85)
    out = merge_blocks([frame(3, cut), frame(12, full)])
    assert len(out) == 1
    assert out[0].latex == full.latex
    assert out[0].first_seen_s == 3
    assert out[0].best_frame_s == 12


def test_partial_seen_after_full_does_not_replace_it() -> None:
    full = blk("and find out its row picture and column picture", conf=0.8)
    later_cut = blk("and find out its row picture", conf=0.99)
    out = merge_blocks([frame(3, full), frame(6, later_cut)])
    assert len(out) == 1
    assert out[0].text == full.text
    assert out[0].best_frame_s == 3


def test_similar_lines_in_the_same_frame_stay_separate() -> None:
    out = merge_blocks([frame(3, blk("x = 2y - 1", "x = 2y - 1"), blk("x = 2y + 1", "x = 2y + 1", bbox=(0.1, 0.3, 0.5, 0.4)))])
    assert len(out) == 2


def test_different_writing_is_not_merged() -> None:
    out = merge_blocks([frame(3, blk("x = 2y - 1", "x = 2y - 1")), frame(6, blk("Row picture", None))])
    assert [b.text for b in out] == ["x = 2y - 1", "Row picture"]


def test_short_fragment_is_not_matched_to_longer_writing() -> None:
    out = merge_blocks([frame(3, blk("x", "x")), frame(6, blk("x = 2y - 1 and so on", "x = 2y - 1"))])
    assert len(out) == 2


def test_ids_are_stable_and_ordered_by_first_seen() -> None:
    readings = [
        frame(9, blk("Column picture", bbox=(0.1, 0.6, 0.5, 0.7)), blk("Row picture", bbox=(0.1, 0.1, 0.5, 0.2))),
        frame(3, blk("Row picture", conf=0.7, bbox=(0.2, 0.1, 0.6, 0.2))),
        frame(6, blk("Two unknowns", bbox=(0.1, 0.3, 0.5, 0.4))),
    ]
    out = merge_blocks(readings)
    assert [(b.id, b.text, b.first_seen_s) for b in out] == [
        ("b_0001", "Row picture", 3),
        ("b_0002", "Two unknowns", 6),
        ("b_0003", "Column picture", 9),
    ]
    assert merge_blocks(list(reversed(readings))) == out


def test_blocks_in_same_frame_are_ordered_top_to_bottom() -> None:
    out = merge_blocks([frame(3, blk("Lower line", bbox=(0.1, 0.8, 0.5, 0.9)), blk("Top heading", bbox=(0.1, 0.05, 0.5, 0.1)))])
    assert [b.text for b in out] == ["Top heading", "Lower line"]


def test_empty_blocks_are_ignored_and_bbox_is_clamped() -> None:
    out = merge_blocks([frame(3, blk("  ", None), blk("Eigenvalues", bbox=(0.6, -0.1, 1.2, 0.2)))])
    assert len(out) == 1
    assert out[0].bbox == [0.6, 0.0, 1.0, 0.2]


def test_no_readings_gives_no_blocks() -> None:
    assert merge_blocks([]) == []


def test_maths_differing_by_one_symbol_stays_separate() -> None:
    steps = [("x^2 + 1 = 0", "x^2+1=0"), ("x^2 + 2 = 0", "x^2+2=0"), ("f(x) = x^2", "f(x)=x^2"), ("f(x) = x^3", "f(x)=x^3")]
    out = merge_blocks([frame(float(i), blk(text, latex)) for i, (text, latex) in enumerate(steps)])
    assert [b.latex for b in out] == [latex for _, latex in steps]


def test_maths_with_brace_and_spacing_differences_still_merges() -> None:
    out = merge_blocks([frame(3, blk("x^2 + 1 = 0", "x^{2} + 1 = 0")), frame(6, blk("x^2+1=0", r"x^2 \, + 1 = 0"))])
    assert len(out) == 1


def test_math_fragment_must_be_an_exact_piece() -> None:
    full = blk("2x + y = 3, x - 2y = -1", r"\begin{cases} 2x + y = 3 \\ x - 2y = -1 \end{cases}")
    out = merge_blocks([frame(3, full), frame(6, blk("2x + y = 4", "2x + y = 4"))])
    assert len(out) == 2


def test_unsure_fragments_of_other_blocks_are_dropped() -> None:
    from app.contracts.ai import BoardBlock
    from app.pipeline.board import drop_fragments

    def b(bid: str, text: str, conf: float, latex: str | None = None) -> BoardBlock:
        return BoardBlock(
            id=bid,
            type="math" if latex else "text",
            text=text,
            latex=latex,
            confidence=conf,
            first_seen_s=0,
            best_frame_s=0,
            bbox=[0, 0, 1, 1],
        )

    blocks = [
        b("b_1", "Row picture:", 0.95),
        b("b_2", "Row", 0.6),  # cut off by the frame edge
        b("b_3", "2x+y=3", 0.9, "2x+y=3"),
        b("b_4", "=3", 0.5, "=3"),
        b("b_5", "Column", 0.9),  # confident: kept even though it is short
    ]
    assert [x.id for x in drop_fragments(blocks)] == ["b_1", "b_3", "b_5"]
