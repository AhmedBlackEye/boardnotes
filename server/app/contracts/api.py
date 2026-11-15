"""Request/response bodies for the HTTP API. The web app's TypeScript types are generated from these."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .ai import AnswerCitation, BoardBlock, SaidNotWritten, TimeRange
from .enums import JobStage, LectureStatus, ReviewDecision, Role, SectionStatus, SuggestionStatus, Verdict


class Api(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- Session ----------
class Me(Api):
    id: str
    name: str
    role: Role
    initials: str


class DemoLogin(Api):
    user_id: str = Field(description="One of the seeded demo users")


# ---------- Lectures ----------
class LectureSummary(Api):
    id: str
    title: str
    duration_s: float | None
    section_count: int
    status: LectureStatus
    open_items: int = Field(description="Open fixes + uncertain items; lecturers see this as 'In review · N'")
    progress: float | None = Field(description="0-1 while processing, else null")
    uploaded_at: datetime


class Bullet(Api):
    id: str
    order: int
    text: str
    latex: str | None
    confidence: float
    uncertain: bool
    board_block_ids: list[str]
    transcript_ranges: list[TimeRange]
    open_suggestions: int


class Section(Api):
    id: str
    order: int
    heading: str
    start_s: float
    end_s: float
    status: SectionStatus
    bullets: list[Bullet]
    said_not_written: list[SaidNotWritten]


class LectureDetail(Api):
    summary: LectureSummary
    sections: list[Section]
    board_blocks: list[BoardBlock]
    video_url: str
    pdf_url: str | None


class TranscriptLine(Api):
    start_s: float
    end_s: float
    speaker: str
    text: str


class SourceView(Api):
    """What the Source panel shows for one bullet."""

    bullet_id: str
    board_blocks: list[BoardBlock]
    snapshot_urls: list[str]
    transcript: list[TranscriptLine]


# ---------- Upload & processing ----------
class UploadInit(Api):
    filename: str
    size_bytes: int = Field(gt=0)
    title: str


class UploadSession(Api):
    upload_id: str
    chunk_size: int
    received_bytes: int


class JobProgress(Api):
    lecture_id: str
    stage: JobStage
    progress: float = Field(ge=0, le=1)
    detail: str
    sections_ready: int
    error: str | None


# ---------- Suggestions, votes, review ----------
class SuggestionCreate(Api):
    bullet_id: str
    proposed_text: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=300)


class Suggestion(Api):
    id: str
    bullet_id: str
    author_name: str
    author_initials: str
    anonymous: bool
    proposed_text: str
    created_at: datetime
    verdict: Verdict | None = Field(description="Null while the AI check is running")
    verdict_reason: str | None
    flagged: bool
    upvotes: int
    voted_by_me: bool
    status: SuggestionStatus


class VoteResult(Api):
    suggestion_id: str
    upvotes: int
    voted_by_me: bool


class ReviewItem(Api):
    id: str = Field(description="Suggestion id, or 'bullet:<id>' for an uncertain reading with no fix")
    lecture_id: str
    section_id: str
    section_heading: str
    bullet_id: str
    current_text: str
    suggestion: Suggestion | None
    board_block: BoardBlock | None
    snapshot_url: str | None
    priority: float = Field(description="See docs/architecture.md#review-priority")


class ReviewDecisionIn(Api):
    decision: ReviewDecision
    edited_text: str | None = Field(default=None, max_length=1000)


# ---------- Ask the lecture ----------
class AskTurn(Api):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(max_length=4000)


class AskIn(Api):
    question: str = Field(min_length=1, max_length=500)
    history: list[AskTurn] = Field(default_factory=list, max_length=6, description="Earlier turns, oldest first, for follow-ups")


class AskOut(Api):
    covered: bool
    answer: str
    citations: list[AnswerCitation]


# ---------- PDFs ----------
class PdfInfo(Api):
    lecture_id: str | None = Field(description="Null for the whole-module PDF")
    title: str
    pages: int
    status: LectureStatus
    generated_at: datetime
    url: str
