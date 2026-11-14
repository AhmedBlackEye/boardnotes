"""Shared enumerations. Changing a value here is a contract change: update docs/decisions.md."""

from enum import StrEnum


class Role(StrEnum):
    STUDENT = "student"
    LECTURER = "lecturer"


class LectureStatus(StrEnum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    DRAFT = "draft"  # notes written, not yet reviewed by the lecturer
    IN_REVIEW = "in_review"  # lecturer has open items
    VERIFIED = "verified"  # every section approved
    FAILED = "failed"


class SectionStatus(StrEnum):
    DRAFT = "draft"
    UNCERTAIN = "uncertain"  # contains at least one low-confidence item
    VERIFIED = "verified"


class JobStage(StrEnum):
    CHECK_VIDEO = "check_video"
    TRANSCRIBE = "transcribe"
    SELECT_FRAMES = "select_frames"
    READ_BOARD = "read_board"
    MERGE_BLOCKS = "merge_blocks"
    SECTION = "section"
    WRITE_NOTES = "write_notes"
    RENDER_PDF = "render_pdf"
    DONE = "done"


class BlockType(StrEnum):
    TEXT = "text"
    MATH = "math"
    DIAGRAM = "diagram"


class Verdict(StrEnum):
    AGREES = "agrees"
    DISAGREES = "disagrees"
    UNCLEAR = "unclear"


class SuggestionStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class CitationKind(StrEnum):
    TRANSCRIPT = "transcript"
    BOARD = "board"
    SECTION = "section"
