"""Boundaries between pipeline stages. Each agent implements one or more of these; the job runner
(server/app/jobs) calls them in order. Keep implementations pure where possible: inputs in, outputs out.

Stage order and owners:
  probe_video        (A)  -> VideoInfo
  extract_audio      (A)  -> Path to mono 16 kHz wav
  transcribe         (C)  -> list[TranscriptSegment]
  select_keyframes   (A)  -> list[Keyframe]            uses LLM tier "glance"
  read_board         (B)  -> list[FrameReading]        uses LLM tier "board"
  merge_blocks       (B)  -> list[BoardBlock]
  plan_sections      (B)  -> SectionPlan               uses LLM tier "notes"
  write_notes        (B)  -> list[SectionNotes]        uses LLM tier "notes"
  validate_citations (B)  -> CitationReport            pure code, no LLM

Phase 3 order (job runner): probe -> extract_audio -> select_keyframes -> transcribe(vocabulary from glance lines)
  -> read_board(transcript) -> merge_blocks -> recheck_formulas -> normalise_terms -> redraw_diagrams
  -> plan_sections -> write_notes -> validate_citations
  render_pdf         (C)  -> bytes                      from LectureDetail
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.contracts.ai import BoardBlock, BoardRead, SectionNotes, SectionPlan, TranscriptSegment
from app.contracts.api import LectureDetail
from app.llm.client import LLM


class VideoCheckError(ValueError):
    """Raised when a video can't be processed. The message is shown to the lecturer."""


@dataclass(frozen=True)
class VideoInfo:
    duration_s: float
    width: int
    height: int
    has_video: bool
    has_audio: bool
    warnings: list[str]  # e.g. "Resolution below 720p: board text may be hard to read"


@dataclass(frozen=True)
class Keyframe:
    time_s: float
    path: Path  # full-resolution JPEG
    lines: list[str]  # text seen in the cheap pass
    readable: float


@dataclass(frozen=True)
class FrameReading:
    keyframe: Keyframe
    read: BoardRead


@dataclass(frozen=True)
class CitationReport:
    valid: list[SectionNotes]  # notes with unsupported bullets removed
    dropped: list[str]  # human-readable reasons, logged and shown in eval
    flagged_bullets: int  # kept but marked uncertain


class Probe(Protocol):
    def __call__(self, video: Path) -> VideoInfo: ...


class AudioExtractor(Protocol):
    def __call__(self, video: Path, out_dir: Path) -> Path: ...


class Transcriber(Protocol):
    async def __call__(self, audio: Path, vocabulary: list[str] | None = None) -> list[TranscriptSegment]: ...

    # vocabulary: terms seen on the board (from the keyframe glance), used to prime speech recognition


class KeyframeSelector(Protocol):
    async def __call__(self, video: Path, out_dir: Path, llm: LLM, interval_s: float) -> list[Keyframe]: ...


class BoardReader(Protocol):
    async def __call__(
        self, keyframes: list[Keyframe], llm: LLM, transcript: list[TranscriptSegment] | None = None
    ) -> list[FrameReading]: ...

    # transcript: speech near each frame is given to the model as untrusted context to resolve unclear writing


class BlockMerger(Protocol):
    def __call__(self, readings: list[FrameReading]) -> list[BoardBlock]: ...


class SectionPlanner(Protocol):
    async def __call__(self, blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: LLM) -> SectionPlan: ...


class NoteWriter(Protocol):
    async def __call__(
        self, plan: SectionPlan, blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: LLM
    ) -> list[SectionNotes]: ...


class CitationValidator(Protocol):
    def __call__(self, notes: list[SectionNotes], blocks: list[BoardBlock], transcript: list[TranscriptSegment]) -> CitationReport: ...


class PdfRenderer(Protocol):
    async def __call__(self, lecture: LectureDetail, include_drafts: bool = True) -> bytes: ...


class FormulaRechecker(Protocol):
    """Re-reads blocks whose formula fails to render (KaTeX), once, at a higher tier. Returns updated blocks."""

    async def __call__(self, blocks: list[BoardBlock], keyframes: list[Keyframe], llm: LLM) -> list[BoardBlock]: ...


class TermNormaliser(Protocol):
    """Makes the same term or symbol read consistently across a lecture's blocks. Generic across subjects."""

    async def __call__(self, blocks: list[BoardBlock], llm: LLM) -> list[BoardBlock]: ...


class DiagramRedrawer(Protocol):
    """Sets BoardBlock.figure for diagram blocks: a validated chart/Mermaid redraw, or a crop of the original."""

    async def __call__(self, blocks: list[BoardBlock], keyframes: list[Keyframe], llm: LLM) -> list[BoardBlock]: ...
