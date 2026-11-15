"""Diagram curation and the notes' chosen figure: blank and repeated drawings are hidden; a chosen figure must be a
real, visible diagram and is shown once per lecture."""

from app.contracts.ai import BoardBlock, ChartElement, ChartSpec, DiagramFigure, NoteBullet, SectionNotes, TimeRange, TranscriptSegment
from app.pipeline.citations import validate_citations
from app.pipeline.diagrams import curate_figures


def chart(caption: str, elements: list[ChartElement]) -> DiagramFigure:
    spec = ChartSpec(title=None, x_label="x", y_label="y", x_range=[-1, 3], y_range=[-2, 4], show_axes=True, elements=elements)
    return DiagramFigure(kind="chart", chart=spec, mermaid=None, caption=caption, redrawn_by_ai=True)


def block(bid: str, t: float, figure: DiagramFigure | None) -> BoardBlock:
    return BoardBlock(
        id=bid, type="diagram", text="axes", latex=None, confidence=0.9, first_seen_s=t, best_frame_s=t, bbox=[0, 0, 1, 1], figure=figure
    )


LABEL_O = ChartElement(type="label", points=[[0, 0]], label="O")
LINE = ChartElement(type="line", points=[[0, 3], [1, 1]], label="2x+y=3")
POINT = ChartElement(type="point", points=[[1, 1]], label="(1,1)")


def test_blank_axes_are_hidden():
    out = curate_figures([block("b_1", 10, chart("Blank x-y axes with origin O", [LABEL_O]))])
    assert out[0].figure is None


def test_repeats_keep_the_most_detailed_drawing():
    blocks = [
        block("b_1", 10, chart("The line 2x + y = 3 on x-y axes", [LINE])),
        block("b_2", 20, chart("The line 2x + y = 3 plotted on x-y axes through (1,1)", [LINE, POINT])),
        block("b_3", 30, chart("A bar chart of exam scores", [ChartElement(type="bar", points=[[1, 5]], label=None)])),
    ]
    out = {b.id: b.figure for b in curate_figures(blocks)}
    assert out["b_1"] is None and out["b_2"] is not None and out["b_3"] is not None


def test_unrelated_and_crop_figures_are_kept():
    crop = DiagramFigure(kind="crop", chart=None, mermaid=None, caption="A sketch", redrawn_by_ai=False)
    out = curate_figures([block("b_1", 5, crop), block("b_2", 9, chart("Vectors u and v", [LINE]))])
    assert all(b.figure is not None for b in out)


def notes(*bullets: NoteBullet) -> SectionNotes:
    return SectionNotes(heading="S", start_s=0, end_s=60, bullets=list(bullets), said_not_written=[])


def bullet(fig: str | None) -> NoteBullet:
    return NoteBullet(
        text="t", latex=None, board_block_ids=[], transcript_ranges=[TimeRange(start_s=1, end_s=5)], confidence=0.9, figure_block_id=fig
    )


def test_chosen_figure_must_be_visible_and_shown_once():
    blocks = [block("b_1", 10, chart("Line", [LINE])), block("b_2", 20, None)]
    transcript = [TranscriptSegment(start_s=0, end_s=10, speaker="lecturer", text="hi")]
    report = validate_citations([notes(bullet("b_1"), bullet("b_1"), bullet("b_2"), bullet("b_9"))], blocks, transcript)
    got = [b.figure_block_id for b in report.valid[0].bullets]
    assert got == ["b_1", None, None, None]
    assert "b_1" in report.valid[0].bullets[0].board_block_ids  # the shown figure is cited too
