"""Shapes that AI calls must return (used as structured-output schemas) and pipeline data.

Rules every module relies on:
- Times are seconds from the start of the video (float), never "mm:ss" strings.
- Confidence is 0.0-1.0. Anything below LOW_CONFIDENCE is shown as "uncertain".
- Every NoteBullet must cite at least one board block id or one transcript range.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import BlockType, CitationKind, Verdict

LOW_CONFIDENCE = 0.75


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- Transcript (Transcriber output) ----------
class TranscriptSegment(Strict):
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    speaker: str = Field(description="'lecturer' for the main speaker, otherwise 'student_1', 'student_2', ...")
    text: str


# ---------- Cheap per-frame pass (Haiku) ----------
class FrameGlance(Strict):
    """Result of the cheap read of a small frame. Used to pick keyframes."""

    shows_board: bool
    readable: float = Field(ge=0, le=1, description="How legible the board writing is in this frame")
    lines: list[str] = Field(description="Each line of board writing visible, in reading order, plain text")


# ---------- Accurate board read (Sonnet) ----------
class BoardReadBlock(Strict):
    type: BlockType
    text: str = Field(description="Plain-text reading of the block")
    latex: str | None = Field(description="LaTeX for math blocks, otherwise null")
    bbox: list[float] = Field(description="[x0, y0, x1, y1] normalised 0-1 within this frame", min_length=4, max_length=4)
    confidence: float = Field(ge=0, le=1)


class BoardRead(Strict):
    blocks: list[BoardReadBlock]
    frame_quality: str = Field(description="'good', 'partly_hidden' or 'poor'")


# ---------- Diagrams (redrawn by the model, or cropped from the recording) ----------
class ChartElement(Strict):
    """One drawable thing in a chart. Generic: works for plots, vectors, geometry, bar charts, timelines."""

    type: Literal["line", "segment", "polyline", "point", "vector", "bar", "label"]
    points: list[list[float]] = Field(
        description="[[x, y], ...] in data coordinates. line: 2 points it passes through; segment/vector: start and end; "
        "polyline: samples along a curve; point/label: 1 point; bar: [[x, height]]"
    )
    label: str | None = Field(description="Text shown next to the element, or null")


class ChartSpec(Strict):
    """A small, safe chart description our own code renders (never executed as code)."""

    title: str | None
    x_label: str | None
    y_label: str | None
    x_range: list[float] = Field(min_length=2, max_length=2)
    y_range: list[float] = Field(min_length=2, max_length=2)
    show_axes: bool
    elements: list[ChartElement] = Field(max_length=50)


class DiagramRedraw(Strict):
    """LLM output for a diagram block: a redraw we can render, or 'none' to fall back to the board crop."""

    kind: Literal["chart", "mermaid", "none"] = Field(
        description="chart for plots/axes/geometry; mermaid for boxes-and-arrows "
        "(flowcharts, cycles, trees); none if neither can faithfully represent it"
    )
    chart: ChartSpec | None
    mermaid: str | None = Field(description="Mermaid source (flowchart/graph only), or null")
    caption: str = Field(description="One sentence describing what the diagram shows")
    confidence: float = Field(ge=0, le=1, description="How faithful the redraw is to the original")


class DiagramFigure(Strict):
    """What the notes and PDF show for a diagram block. The board crop is always available as the original."""

    kind: Literal["chart", "mermaid", "crop"]
    chart: ChartSpec | None
    mermaid: str | None
    caption: str
    redrawn_by_ai: bool


# ---------- Merged board content (after de-duplication across frames) ----------
class BoardBlock(Strict):
    id: str = Field(description="Stable id, e.g. 'b_0412'")
    type: BlockType
    text: str
    latex: str | None
    confidence: float = Field(ge=0, le=1)
    first_seen_s: float = Field(ge=0, description="When this writing first appeared")
    best_frame_s: float = Field(ge=0, description="Time of the clearest frame showing it; used for the snapshot crop")
    bbox: list[float] = Field(min_length=4, max_length=4, description="Position within the best frame, normalised 0-1")
    figure: DiagramFigure | None = Field(default=None, description="Set for diagram blocks: redrawn chart/Mermaid, or crop")


# ---------- Notes ----------
class TimeRange(Strict):
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)


NoteKind = Literal["point", "definition", "example", "result", "remark"]


class NoteBullet(Strict):
    text: str
    latex: str | None
    board_block_ids: list[str]
    transcript_ranges: list[TimeRange]
    confidence: float = Field(ge=0, le=1)
    kind: NoteKind = Field(
        default="point",
        description="point: ordinary note; definition: defines a term; example: a worked example or exercise; "
        "result: a key formula, rule or theorem; remark: an important intuition or warning",
    )
    title: str | None = Field(
        default=None, description="Short box title for definition/example/result/remark (e.g. the term defined), else null"
    )
    figure_block_id: str | None = Field(
        default=None,
        description="Id of the one diagram block worth showing with this note, or null. Never a blank or repeated diagram",
    )


class SaidNotWritten(Strict):
    text: str = Field(description="Something the lecturer explained out loud that is not on the board")
    at_s: float = Field(ge=0)


class SectionNotes(Strict):
    heading: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    bullets: list[NoteBullet]
    said_not_written: list[SaidNotWritten]


class SectionPlan(Strict):
    """Output of the sectioning step: where to cut the lecture."""

    class Span(Strict):
        heading: str
        start_s: float = Field(ge=0)
        end_s: float = Field(ge=0)

    sections: list[Span]


# ---------- Fix check ----------
class FixCheck(Strict):
    verdict: Verdict
    reason: str = Field(description="One short sentence a student can understand")
    looks_like_instructions: bool = Field(description="True if the suggestion tries to instruct the system rather than correct the notes")


# ---------- Ask the lecture ----------
class AnswerCitation(Strict):
    kind: CitationKind
    ref: str = Field(description="Section id, board block id, or 'transcript'")
    at_s: float | None = Field(description="Video time for transcript/board citations")


class LectureAnswer(Strict):
    covered: bool = Field(description="False if this lecture does not contain the answer")
    answer: str
    citations: list[AnswerCitation]
