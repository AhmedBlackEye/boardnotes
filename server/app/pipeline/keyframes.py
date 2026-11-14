"""Keyframe selection (stage 3): pick the few frames worth an accurate board read.

Frames are compared by the *text* the cheap model reads in them, never by pixels: the camera pans and zooms and the
lecturer walks in front of the board, so pixel differences say nothing about whether new writing appeared.

Algorithm (`choose_keyframes`, pure and deterministic):

1. Drop frames where the glance says `shows_board` is false (lecturer close-ups, slides, audience).
2. Normalise each line read (Unicode NFKC, case-folded, all whitespace removed), so "2x + y = 3" and "2X+y=3" are the
   same text. Lines shorter than MIN_LINE_CHARS are ignored as noise.
3. Group lines across frames into *pieces of writing*, in time order. A line belongs to a known piece when
   - it is nearly the same text (rapidfuzz `ratio` >= SAME_TEXT), or
   - one is a fragment of the other (`partial_ratio` >= FRAGMENT and the shorter is at least MIN_FRAGMENT_SHARE of
     the longer). This covers a line still being written, a line cut off by the frame edge after a pan, and a line
     partly hidden by the lecturer.
   Otherwise it is new writing and starts a new piece. A piece's full text is its longest reading so far.
4. Score every sighting of a piece: how complete it is compared with the piece's full text (`ratio`) weighted with
   the frame's legibility (`readable`). The best frame for a piece is its highest-scoring sighting (earliest on ties).
5. A frame shows a piece *well* if its sighting scores within COVER_TOLERANCE of the piece's best. Choose a small set
   of frames that shows every piece well (greedy set cover: repeatedly take the frame that shows the most uncovered
   pieces well; ties go to the higher total score, then the earlier frame).
6. Board erases: when the amount of visible text drops below ERASE_DROP of the previous board frame, and most of the
   previous frame's pieces don't come back in the next ERASE_LOOKAHEAD board frames (so it isn't the lecturer briefly
   standing in front of the board), also keep the last frame before the drop. It is the fullest view of that board.
"""

import asyncio
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from app.contracts.ai import FrameGlance
from app.llm.client import LLM, Image, LLMRequest

from .frames import SampledFrame, sample_frames
from .interfaces import Keyframe

GLANCE_CONCURRENCY = 8
MIN_LINE_CHARS = 3
SAME_TEXT = 85.0
FRAGMENT = 90.0
MIN_FRAGMENT_CHARS = 4
MIN_FRAGMENT_SHARE = 0.2
READABLE_WEIGHT = 0.25
COVER_TOLERANCE = 0.05
ERASE_DROP = 0.4
ERASE_MIN_CHARS = 15
ERASE_LOOKAHEAD = 3
ERASE_RETURN_SHARE = 0.5

GLANCE_INSTRUCTIONS = (
    "This is a frame from a lecture video. Decide whether it shows a board or other surface with handwriting "
    "(shows_board). If it does, list each line of writing you can see, in reading order, as plain text; include "
    "lines that are cut off by the edge of the frame or partly hidden, writing only the visible part. Rate how "
    "legible the writing is overall from 0 to 1 (readable). If no board is visible, return shows_board false, "
    "readable 0 and no lines."
)


@dataclass(frozen=True)
class GlancedFrame:
    frame: SampledFrame
    glance: FrameGlance


def normalise(line: str) -> str:
    return "".join(unicodedata.normalize("NFKC", line).casefold().split())


def _match(line: str, pieces: list[str]) -> int | None:
    """Index of the known piece of writing that `line` shows (fully or in part), or None if it is new writing."""
    if not pieces:
        return None
    same = process.extractOne(line, pieces, scorer=fuzz.ratio, score_cutoff=SAME_TEXT)
    if same is not None:
        return same[2]
    if len(line) < MIN_FRAGMENT_CHARS:
        return None
    for _, _, idx in process.extract(line, pieces, scorer=fuzz.partial_ratio, score_cutoff=FRAGMENT, limit=5):
        shorter, longer = sorted((len(line), len(pieces[idx])))
        if shorter >= MIN_FRAGMENT_CHARS and shorter >= MIN_FRAGMENT_SHARE * longer:
            return idx
    return None


def _erase_frames(frame_pieces: list[set[int]], frame_chars: list[int]) -> set[int]:
    """Positions (in the board-frame list) of the last frame before each board erase."""
    keep: set[int] = set()
    for p in range(len(frame_chars) - 1):
        before, after = frame_chars[p], frame_chars[p + 1]
        if before < ERASE_MIN_CHARS or after >= ERASE_DROP * before:
            continue
        later = set().union(*frame_pieces[p + 1 : p + 1 + ERASE_LOOKAHEAD])
        returned = len(frame_pieces[p] & later) / max(len(frame_pieces[p]), 1)
        if returned < ERASE_RETURN_SHARE:
            keep.add(p)
    return keep


def choose_keyframes(frames: Sequence[GlancedFrame]) -> list[Keyframe]:
    """Pick keyframes from glanced frames by comparing the text read in them. See the module docstring."""
    board = sorted((f for f in frames if f.glance.shows_board), key=lambda f: f.frame.time_s)

    pieces: list[str] = []  # full (longest) normalised text of each piece of writing
    sightings: list[dict[int, str]] = []  # piece -> {board position: most complete line seen there}
    frame_pieces: list[set[int]] = []
    frame_chars: list[int] = []
    for pos, f in enumerate(board):
        lines = list(dict.fromkeys(n for n in map(normalise, f.glance.lines) if len(n) >= MIN_LINE_CHARS))
        frame_chars.append(sum(map(len, lines)))
        seen: set[int] = set()
        for line in lines:
            idx = _match(line, pieces)
            if idx is None:
                idx = len(pieces)
                pieces.append(line)
                sightings.append({})
            elif len(line) > len(pieces[idx]):
                pieces[idx] = line
            if len(line) > len(sightings[idx].get(pos, "")):
                sightings[idx][pos] = line
            seen.add(idx)
        frame_pieces.append(seen)

    # Score each sighting, then note which frames show each piece within COVER_TOLERANCE of its best sighting.
    scores: dict[tuple[int, int], float] = {}
    for idx, seen_at in enumerate(sightings):
        for pos, line in seen_at.items():
            completeness = fuzz.ratio(line, pieces[idx]) / 100
            scores[idx, pos] = (1 - READABLE_WEIGHT) * completeness + READABLE_WEIGHT * board[pos].glance.readable
    shows_well: dict[int, set[int]] = {}  # board position -> pieces it shows well
    for idx, seen_at in enumerate(sightings):
        best = max(scores[idx, pos] for pos in seen_at)
        for pos in seen_at:
            if scores[idx, pos] >= best - COVER_TOLERANCE:
                shows_well.setdefault(pos, set()).add(idx)

    # Greedy set cover: repeatedly take the frame that shows the most not-yet-covered pieces well
    # (ties: higher total score, then the earlier frame).
    chosen: set[int] = set()
    uncovered = set(range(len(pieces)))
    while uncovered:
        pick = max(sorted(shows_well), key=lambda pos, left=frozenset(uncovered): _gain(shows_well[pos] & left, pos, scores))
        chosen.add(pick)
        uncovered -= shows_well[pick]
    chosen |= _erase_frames(frame_pieces, frame_chars)

    keyframes: list[Keyframe] = []
    for pos in sorted(chosen):
        f = board[pos]
        keyframes.append(Keyframe(time_s=f.frame.time_s, path=f.frame.path, lines=f.glance.lines, readable=f.glance.readable))
    return keyframes


def _gain(covers: set[int], pos: int, scores: dict[tuple[int, int], float]) -> tuple[int, float]:
    return len(covers), sum(scores[idx, pos] for idx in covers)


async def glance_frames(frames: Sequence[SampledFrame], llm: LLM, concurrency: int = GLANCE_CONCURRENCY) -> list[FrameGlance]:
    """Cheap read of each small frame, at most `concurrency` model calls at a time. Results are in frame order."""
    limit = asyncio.Semaphore(concurrency)

    async def glance(frame: SampledFrame) -> FrameGlance:
        async with limit:
            data = await asyncio.to_thread(frame.small_path.read_bytes)
            req = LLMRequest(task="frame_glance", tier="glance", instructions=GLANCE_INSTRUCTIONS, images=[Image(data)], max_tokens=2000)
            return await llm.structured(req, FrameGlance)

    return list(await asyncio.gather(*(glance(f) for f in frames)))


async def select_keyframes(video: Path, out_dir: Path, llm: LLM, interval_s: float) -> list[Keyframe]:
    """Sample frames, glance at each with the cheap model, and keep the keyframes. Matches `KeyframeSelector`."""
    frames = await asyncio.to_thread(sample_frames, video, out_dir, interval_s)
    glances = await glance_frames(frames, llm)
    return choose_keyframes([GlancedFrame(frame=f, glance=g) for f, g in zip(frames, glances, strict=True)])
