"""Board stages: read each keyframe accurately (B-1) and merge the same writing across frames (B-2)."""

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field

from PIL import Image as PILImage
from rapidfuzz import fuzz

from app.contracts.ai import BoardBlock, BoardRead, BoardReadBlock, TranscriptSegment
from app.contracts.enums import BlockType
from app.llm.anthropic_llm import RefusedError
from app.llm.client import LLM, Image, LLMRequest

from .interfaces import FrameReading, Keyframe

log = logging.getLogger(__name__)

MAX_EDGE_PX = 1568  # long-edge limit for vision input; larger images are downscaled
READ_CONCURRENCY = 6
READ_ATTEMPTS = 2  # first try + one retry
RETRY_BACKOFF_S = 2.0  # wait before a retry, times the attempt number
MAX_IMAGE_PIXELS = 40_000_000  # refuse to decode anything bigger (ffmpeg frames are far smaller)
SPEECH_BEFORE_S = 20.0  # speech from this long before a frame can explain what is on the board ...
SPEECH_AFTER_S = 10.0  # ... and from shortly after it (lecturers often read out what they have just written)


class BoardReadError(RuntimeError):
    """Raised when no keyframe at all could be read, so the lecture would otherwise come out silently empty."""


BOARD_READ_INSTRUCTIONS = """\
You are transcribing the writing on a lecture blackboard or whiteboard from one video frame.

Read every distinct piece of writing on the board and return it as blocks, in reading order
(top to bottom, then left to right; for boards split into panels, finish one panel before the next).

Blocks
- One block per visually separate unit: an equation or derivation step, a line or short paragraph of text,
  a heading, or a diagram. Do not merge writing from different panels into one block.
- type "math" for anything mathematical (equations, expressions, matrices, inequalities, set notation);
  "text" for words; "diagram" for drawings, graphs and sketches.
- text: a plain-text reading of the block exactly as written (for a diagram, a short description of what it shows
  and any labels on it).
- latex: for math blocks, valid KaTeX-compatible LaTeX of exactly what is written, without surrounding $ signs.
  Use environments such as cases, pmatrix, bmatrix and aligned where the board uses them. null for text and diagrams.
- bbox: [x0, y0, x1, y1] of the block within this frame, normalised 0-1 with (0, 0) at the top-left.

Handwriting (chalk and marker)
- Transcribe what is written, not what you think should be written. Do not correct the lecturer's maths,
  complete derivations, or add steps that are not on the board.
- Watch for common confusions: 1/l/I, 0/O, 2/z/Z, 5/s/S, x/× (times), u/v, n/h, a/α, B/β, t/+, minus signs vs dashes,
  primes vs commas, subscripts vs exponents. Decide using the surrounding maths.
- Skip faint ghosts of erased writing, smudges and reflections.
- If writing is cut off by the frame edge or hidden by the lecturer, transcribe only the visible part
  and lower its confidence; do not guess the hidden part.

Confidence (0-1, be calibrated)
- 0.95+: every symbol clearly legible.
- 0.8-0.95: legible, but one or two symbols needed context to decide.
- 0.5-0.8: partly hidden, cut off, blurry or ambiguous; the reading may be wrong in places.
- below 0.5: mostly a guess.

frame_quality: "good" if the board is clearly visible; "partly_hidden" if the lecturer, glare or the frame edge hides
part of the writing; "poor" if blur, lighting or distance makes most of it hard to read.
If the frame shows no board writing, return no blocks and frame_quality "poor".

A cheaper first pass listed lines it thought were visible; they are given as data below and may be wrong or incomplete.
Use them only as a hint, and read the image yourself."""

SPEECH_HINT = """

What the lecturer said around the time of this frame is also given as data below (an automatic transcript, which may
contain mistakes). Use it only to decide between readings of writing that is unclear on the board (for example a
symbol or word that is hard to make out). Never add content that is not written on the board, and never change
clearly legible writing to match the speech."""


def nearby_speech(transcript: list[TranscriptSegment], time_s: float) -> str:
    """Transcript text spoken from SPEECH_BEFORE_S before to SPEECH_AFTER_S after `time_s`, one segment per line."""
    start, end = time_s - SPEECH_BEFORE_S, time_s + SPEECH_AFTER_S
    lines = [s.text.strip() for s in sorted(transcript, key=lambda s: s.start_s) if s.end_s >= start and s.start_s <= end]
    return "\n".join(line for line in lines if line)


def load_image(data: bytes) -> Image:
    """Return the image for the model, downscaled so the long edge is at most MAX_EDGE_PX."""
    with PILImage.open(io.BytesIO(data)) as img:
        if img.size[0] * img.size[1] > MAX_IMAGE_PIXELS:
            raise ValueError(f"frame is too large ({img.size[0]}x{img.size[1]})")
        fmt = img.format
        if max(img.size) <= MAX_EDGE_PX and fmt in ("JPEG", "PNG"):
            return Image(data=data, media_type="image/jpeg" if fmt == "JPEG" else "image/png")
        rgb = img.convert("RGB")
        rgb.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), PILImage.Resampling.LANCZOS)
        out = io.BytesIO()
        rgb.save(out, format="JPEG", quality=92)
        return Image(data=out.getvalue(), media_type="image/jpeg")


def board_read_request(keyframe: Keyframe, image: Image, speech: str = "") -> LLMRequest:
    """Request for one frame. Speech near the frame, if any, goes in untrusted data like the first-pass lines."""
    untrusted = {"first_pass_lines": "\n".join(keyframe.lines)}
    if speech:
        untrusted["nearby_speech"] = speech
    return LLMRequest(
        task="board_read",
        tier="board",
        instructions=BOARD_READ_INSTRUCTIONS + (SPEECH_HINT if speech else ""),
        untrusted=untrusted,
        images=[image],
        effort="low",
    )


async def _read_one(keyframe: Keyframe, llm: LLM, sem: asyncio.Semaphore, speech: str) -> FrameReading | None:
    async with sem:
        try:
            data = await asyncio.to_thread(keyframe.path.read_bytes)
            image = await asyncio.to_thread(load_image, data)
        except Exception:
            log.exception("board_read: cannot load frame at %.1fs (%s); skipping", keyframe.time_s, keyframe.path)
            return None
        req = board_read_request(keyframe, image, speech)
        for attempt in range(1, READ_ATTEMPTS + 1):
            try:
                read = await llm.structured(req, BoardRead)
                return FrameReading(keyframe=keyframe, read=read)
            except RefusedError as exc:
                log.warning("board_read: frame at %.1fs refused, not retrying: %s", keyframe.time_s, exc)
                return None
            except Exception as exc:
                log.warning("board_read: frame at %.1fs failed (attempt %d/%d): %s", keyframe.time_s, attempt, READ_ATTEMPTS, exc)
                if attempt < READ_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_S * attempt)
        log.error("board_read: skipping frame at %.1fs after %d attempts", keyframe.time_s, READ_ATTEMPTS)
        return None


async def read_board(keyframes: list[Keyframe], llm: LLM, transcript: list[TranscriptSegment] | None = None) -> list[FrameReading]:
    """Read every keyframe at full resolution. Frames that fail twice are skipped. Output is in time order.

    If a transcript is given, the speech around each frame is passed as untrusted data to help resolve unclear writing.
    Raises BoardReadError if there were keyframes but none could be read."""
    sem = asyncio.Semaphore(READ_CONCURRENCY)
    segments = transcript or []
    results = await asyncio.gather(*(_read_one(kf, llm, sem, nearby_speech(segments, kf.time_s)) for kf in keyframes))
    readings = sorted((r for r in results if r is not None), key=lambda r: r.keyframe.time_s)
    if keyframes and not readings:
        raise BoardReadError(f"none of the {len(keyframes)} keyframes could be read")
    if len(readings) < len(keyframes) / 2:
        log.warning("board_read: only %d of %d keyframes could be read", len(readings), len(keyframes))
    return readings


# ---------- B-2: merge readings across frames ----------

SAME_RATIO = 85.0  # full-string similarity (0-100) for two readings of the same writing
PARTIAL_RATIO = 92.0  # similarity of the shorter reading to the best-matching part of the longer one
PARTIAL_MIN_CHARS = 6  # shorter readings can't be matched as fragments (too many false hits)
PARTIAL_MIN_SHARE = 0.4  # ... nor can fragments shorter than this share of the longer reading
FULLER_SHARE = 0.9  # a reading under this share of a matching reading's length is treated as partial

_LATEX_NOISE = re.compile(r"\\(left|right|big|Big|bigg|Bigg|displaystyle|,|;|:|!|quad|qquad)(?![a-zA-Z])")
_NON_KEY = re.compile(r"[^\w\\{}^_=+\-*/<>()\[\]|]")
_SINGLE_BRACED = re.compile(r"\{(\w)\}")  # x^{2} -> x^2, \frac{1}{2} -> \frac12


def normalise(text: str) -> str:
    """Comparison key for a reading: lowercase, no spacing commands, whitespace or decorative punctuation."""
    key = _LATEX_NOISE.sub("", text.lower())
    key = key.replace("\u2212", "-").replace("\u00d7", "*").replace("\\cdot", "*").replace("\\times", "*")
    return _NON_KEY.sub("", key)


def _keys(block: BoardReadBlock) -> list[str]:
    keys = [normalise(block.text)]
    if block.latex:
        keys.append(normalise(block.latex))
    if is_math(block):
        keys = [_SINGLE_BRACED.sub(r"\1", k) for k in keys]
    return [k for k in keys if k]


def is_math(block: BoardReadBlock) -> bool:
    return block.type == BlockType.MATH or bool(block.latex)


def _is_fragment(short: str, long: str) -> bool:
    if len(short) < PARTIAL_MIN_CHARS or len(short) < PARTIAL_MIN_SHARE * len(long):
        return False
    return fuzz.partial_ratio(short, long) >= PARTIAL_RATIO


def _strict_score(ka: str, kb: str) -> float:
    """Maths: one symbol changes the meaning (x^2+1=0 vs x^2+2=0), so only identical keys, or a key that is an exact
    piece of the other (cut off by the frame edge, or still being written), count as the same writing."""
    if ka == kb:
        return 100.0
    short, long = sorted((ka, kb), key=len)
    if len(short) >= PARTIAL_MIN_CHARS and len(short) >= PARTIAL_MIN_SHARE * len(long) and short in long:
        return 100.0
    return 0.0


def similarity(a: list[str], b: list[str], *, strict: bool = False) -> float:
    """Best match score (0-100) between two readings over their text/LaTeX keys; 0 if they look different.

    strict (for maths) allows no edits: see _strict_score."""
    best = 0.0
    for ka in a:
        for kb in b:
            if strict:
                best = max(best, _strict_score(ka, kb))
                continue
            score = fuzz.ratio(ka, kb)
            if score < SAME_RATIO:
                short, long = sorted((ka, kb), key=len)
                score = fuzz.partial_ratio(short, long) if _is_fragment(short, long) else 0.0
            best = max(best, score)
    return best if best >= SAME_RATIO else 0.0


@dataclass
class _Sighting:
    time_s: float
    block: BoardReadBlock
    keys: list[str]

    @property
    def length(self) -> int:
        return max(len(k) for k in self.keys)


def is_better(a: _Sighting, b: _Sighting) -> bool:
    """True if `a` is a better reading of the writing than `b`: fuller first, then more confident, then earlier."""
    if a.length < FULLER_SHARE * b.length:
        return False
    if b.length < FULLER_SHARE * a.length:
        return True
    return (a.block.confidence, a.length, -a.time_s) > (b.block.confidence, b.length, -b.time_s)


@dataclass
class _Cluster:
    best: _Sighting
    first_seen_s: float
    frames: set[float] = field(default_factory=set)

    def add(self, s: _Sighting) -> None:
        self.first_seen_s = min(self.first_seen_s, s.time_s)
        self.frames.add(s.time_s)
        if is_better(s, self.best):
            self.best = s


def _clamp_bbox(bbox: list[float]) -> list[float]:
    x0, y0, x1, y1 = (min(max(v, 0.0), 1.0) for v in bbox)
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def merge_blocks(readings: list[FrameReading]) -> list[BoardBlock]:
    """Collapse the same writing seen in many frames into one block per piece of writing.

    Readings are matched by normalised text/LaTeX (not position, since the camera moves). A reading that is a fragment
    of a longer one (cut off by the frame edge, or still being written) joins the same block; the fullest, most
    confident reading wins. Maths is matched strictly (no edits allowed), so derivation steps that differ by one
    symbol stay separate blocks. Ids are assigned b_0001, b_0002, ... in order of first appearance.
    """
    clusters: list[_Cluster] = []
    for reading in sorted(readings, key=lambda r: r.keyframe.time_s):
        t = reading.keyframe.time_s
        for block in reading.read.blocks:
            keys = _keys(block)
            if not keys:
                continue
            sighting = _Sighting(time_s=t, block=block, keys=keys)
            # Two blocks in the same frame are different writing, so a cluster takes at most one block per frame.
            candidates = [
                (similarity(keys, c.best.keys, strict=is_math(block) or is_math(c.best.block)), i)
                for i, c in enumerate(clusters)
                if t not in c.frames
            ]
            score, index = max(candidates, default=(0.0, -1))
            if score > 0:
                clusters[index].add(sighting)
            else:
                clusters.append(_Cluster(best=sighting, first_seen_s=t, frames={t}))

    clusters.sort(key=lambda c: (c.first_seen_s, c.best.block.bbox[1], c.best.block.bbox[0]))
    return [
        BoardBlock(
            id=f"b_{n:04d}",
            type=c.best.block.type,
            text=c.best.block.text,
            latex=c.best.block.latex,
            confidence=c.best.block.confidence,
            first_seen_s=c.first_seen_s,
            best_frame_s=c.best.time_s,
            bbox=_clamp_bbox(c.best.block.bbox),
        )
        for n, c in enumerate(clusters, start=1)
    ]
