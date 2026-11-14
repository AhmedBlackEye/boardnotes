"""Shapes that AI calls must return (used as structured-output schemas) and pipeline data.

Rules every module relies on:
- Times are seconds from the start of the video (float), never "mm:ss" strings.
- Confidence is 0.0-1.0. Anything below LOW_CONFIDENCE is shown as "uncertain".
- Every NoteBullet must cite at least one board block id or one transcript range.
"""

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


# ---------- Notes ----------
class TimeRange(Strict):
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)


class NoteBullet(Strict):
    text: str
    latex: str | None
    board_block_ids: list[str]
    transcript_ranges: list[TimeRange]
    confidence: float = Field(ge=0, le=1)


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
