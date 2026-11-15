"""Stage: transcribe the lecture audio into timestamped, speaker-labelled segments.

`transcribe(audio, vocabulary)` is the pipeline entry point (`Transcriber`). The provider is chosen by
`settings.transcriber` (env TRANSCRIBER):
  - "fixture": the recorded transcript in fixtures/transcript.json, so the pipeline runs offline.
  - "fal": fal's hosted Whisper (`fal-ai/whisper`), word timestamps + diarization; the board vocabulary is passed as
    Whisper's prompt so technical terms are spelled the way they are written on the board.
  - "elevenlabs": ElevenLabs Scribe, word timestamps + diarization (vocabulary is not used).
Unset, it is "fixture" with LLM_MODE=fake and "elevenlabs" with LLM_MODE=live. A real provider without its key raises
rather than silently using the fixture.

Responses become segments through pure functions: `segments_from_response` (Scribe) and `segments_from_fal` (Whisper).
"""

import asyncio
import json
import logging
import subprocess  # noqa: S404 - fixed argument list, never a shell
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from app.config import REPO_ROOT, settings
from app.contracts.ai import TranscriptSegment

log = logging.getLogger(__name__)

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
SCRIBE_MODEL = "scribe_v2"
FAKE_TRANSCRIPT = REPO_ROOT / "fixtures" / "transcript.json"

FAL_MODEL = "fal-ai/whisper"
FAL_QUEUE_URL = "https://queue.fal.run"
FAL_STORAGE_URL = "https://rest.fal.ai/storage/upload/initiate"
FAL_SINGLE_UPLOAD_MAX_BYTES = 90 * 1024**2  # larger files need fal's multipart upload: we re-encode instead
FAL_POLL_S = 3.0  # time between queue status checks
FAL_TIMEOUT_S = 1800.0  # give up on a transcription after this long (upload + queue + run)
FAL_HTTP_TIMEOUT = httpx.Timeout(300.0, connect=30.0)

VOCAB_MAX_TERMS = 40
VOCAB_MAX_CHARS = 400  # Whisper's prompt window is ~224 tokens; keep well inside it
VOCAB_MAX_TERM_CHARS = 60  # longer board lines are sentences, not terms

MAX_SEGMENT_S = 15.0  # hard cap on a segment's length
PAUSE_SPLIT_S = 1.5  # a silence this long always starts a new segment
SENTENCE_SPLIT_AFTER_S = 8.0  # once a segment is this long, end it at the next sentence end
SENTENCE_ENDINGS = (".", "?", "!")
UNKNOWN_SPEAKER = "unknown"

TranscriberName = Literal["fixture", "fal", "elevenlabs"]


class TranscriptionError(RuntimeError):
    """Speech-to-text failed. The message names the provider and step, never the API key."""


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float
    speaker: str


# ---------- Grouping words into segments (shared by every provider) ----------
def speaker_labels(words: Sequence[_Word]) -> dict[str, str]:
    """Map raw speaker ids to 'lecturer' (most speech time) and 'student_1', 'student_2', ... (by first appearance)."""
    talk: dict[str, float] = {}
    for w in words:
        talk[w.speaker] = talk.get(w.speaker, 0.0) + (w.end - w.start)
    if not talk:
        return {}
    # Ties go to whoever spoke first (dicts keep insertion order and max() returns the first maximum).
    lecturer = max(talk, key=lambda s: talk[s])
    labels = {lecturer: "lecturer"}
    for n, speaker in enumerate((s for s in talk if s != lecturer), start=1):
        labels[speaker] = f"student_{n}"
    return labels


def _segment(words: Sequence[_Word], speaker: str) -> TranscriptSegment:
    return TranscriptSegment(start_s=words[0].start, end_s=words[-1].end, speaker=speaker, text=" ".join(w.text for w in words))


def group_words(
    words: Sequence[_Word], max_segment_s: float = MAX_SEGMENT_S, pause_split_s: float = PAUSE_SPLIT_S
) -> list[TranscriptSegment]:
    """Group time-ordered words into segments of at most ~max_segment_s seconds.

    A new segment starts when the speaker changes, after a pause of pause_split_s or more, at a sentence end once
    the segment is reasonably long, or when adding the next word would exceed max_segment_s.
    """
    labels = speaker_labels(words)
    segments: list[TranscriptSegment] = []
    current: list[_Word] = []
    for w in words:
        if current:
            prev = current[-1]
            length = prev.end - current[0].start
            split = (
                w.speaker != prev.speaker
                or w.start - prev.end >= pause_split_s
                or w.end - current[0].start > max_segment_s
                or (length >= min(SENTENCE_SPLIT_AFTER_S, max_segment_s) and prev.text.endswith(SENTENCE_ENDINGS))
            )
            if split:
                segments.append(_segment(current, labels[prev.speaker]))
                current = []
        current.append(w)
    if current:
        segments.append(_segment(current, labels[current[-1].speaker]))
    return segments


# ---------- ElevenLabs Scribe ----------
def _scribe_words(response: Mapping[str, Any]) -> list[_Word]:
    """Spoken words with timestamps, in time order. Spacing tokens and audio events are dropped."""
    out: list[_Word] = []
    for w in response.get("words") or []:
        if w.get("type") != "word" or w.get("start") is None or w.get("end") is None:
            continue
        text = str(w.get("text", "")).strip()
        if not text:
            continue
        start = max(0.0, float(w["start"]))
        end = max(start, float(w["end"]))
        out.append(_Word(text=text, start=start, end=end, speaker=str(w.get("speaker_id") or UNKNOWN_SPEAKER)))
    out.sort(key=lambda w: w.start)
    return out


def segments_from_response(
    response: Mapping[str, Any],
    max_segment_s: float = MAX_SEGMENT_S,
    pause_split_s: float = PAUSE_SPLIT_S,
) -> list[TranscriptSegment]:
    """Scribe response -> segments (see `group_words`)."""
    return group_words(_scribe_words(response), max_segment_s, pause_split_s)


async def request_scribe(audio: Path, api_key: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """POST the audio to ElevenLabs speech-to-text and return the JSON response."""
    data = {
        "model_id": SCRIBE_MODEL,
        "diarize": "true",
        "timestamps_granularity": "word",
        "tag_audio_events": "false",
    }
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(1800.0, connect=30.0))
    try:
        with audio.open("rb") as f:
            resp = await http.post(
                ELEVENLABS_STT_URL,
                headers={"xi-api-key": api_key},
                data=data,
                files={"file": (audio.name, f, "audio/wav")},
            )
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            await http.aclose()


# ---------- fal Whisper ----------
def vocabulary_prompt(vocabulary: Iterable[str] | None) -> str:
    """Board terms as a short Whisper prompt: whitespace-normalised, deduplicated (case-insensitive), in first-seen
    order, skipping long lines, and capped at VOCAB_MAX_TERMS terms / VOCAB_MAX_CHARS characters."""
    terms: list[str] = []
    seen: set[str] = set()
    length = 0
    for raw in vocabulary or []:
        term = " ".join(str(raw).split())
        key = term.casefold()
        if not term or len(term) > VOCAB_MAX_TERM_CHARS or key in seen:
            continue
        added = len(term) + (2 if terms else 0)  # ", " separator
        if len(terms) >= VOCAB_MAX_TERMS or length + added > VOCAB_MAX_CHARS:
            break
        seen.add(key)
        terms.append(term)
        length += added
    return ", ".join(terms)


def _float_or_none(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _span(item: Mapping[str, Any]) -> tuple[float | None, float | None]:
    ts = item.get("timestamp")
    if not isinstance(ts, Sequence) or isinstance(ts, str):
        return None, None
    start = _float_or_none(ts[0]) if len(ts) > 0 else None
    end = _float_or_none(ts[1]) if len(ts) > 1 else None
    return start, end


def _overlap_speaker(start: float, end: float, turns: Sequence[tuple[float, float, str]]) -> str | None:
    """Speaker of the diarization turn that overlaps [start, end] the most (or contains `start` for a 0-length word)."""
    best: str | None = None
    best_overlap = -1.0
    for t_start, t_end, speaker in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap and (overlap > 0 or t_start <= start <= t_end):
            best, best_overlap = speaker, overlap
    return best


def _fal_words(response: Mapping[str, Any]) -> list[_Word]:
    """Whisper chunks -> words in time order.

    A chunk without an end time (Whisper leaves the last one open) ends where the next chunk starts, or at its start.
    A chunk's speaker is its own `speaker`, else the most-overlapping diarization turn, else the previous word's
    speaker; without diarization everyone is one speaker (who becomes 'lecturer').
    """
    turns: list[tuple[float, float, str]] = []
    for t in response.get("diarization_segments") or []:
        t_start, t_end = _span(t)
        if t_start is not None and t_end is not None and t.get("speaker"):
            turns.append((t_start, t_end, str(t["speaker"])))

    raw: list[tuple[float, float | None, str, str | None]] = []
    for c in response.get("chunks") or []:
        start, end = _span(c)
        text = str(c.get("text") or "").strip()
        if start is None or not text:
            continue
        raw.append((max(0.0, start), end, text, str(c["speaker"]) if c.get("speaker") else None))
    raw.sort(key=lambda r: r[0])

    out: list[_Word] = []
    for i, (start, end, text, speaker) in enumerate(raw):
        if end is None:
            end = raw[i + 1][0] if i + 1 < len(raw) else start
        end = max(start, end)
        speaker = speaker or _overlap_speaker(start, end, turns) or (out[-1].speaker if out else UNKNOWN_SPEAKER)
        out.append(_Word(text=text, start=start, end=end, speaker=speaker))
    return out


def segments_from_fal(
    response: Mapping[str, Any],
    max_segment_s: float = MAX_SEGMENT_S,
    pause_split_s: float = PAUSE_SPLIT_S,
) -> list[TranscriptSegment]:
    """fal Whisper response -> segments (see `group_words`)."""
    return group_words(_fal_words(response), max_segment_s, pause_split_s)


def fal_input(audio_url: str, vocabulary: Iterable[str] | None) -> dict[str, Any]:
    """Request body for fal-ai/whisper."""
    body: dict[str, Any] = {"audio_url": audio_url, "task": "transcribe", "chunk_level": "word", "diarize": True}
    prompt = vocabulary_prompt(vocabulary)
    if prompt:
        body["prompt"] = prompt
    return body


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        detail = body.get("detail", body) if isinstance(body, dict) else body
        text = json.dumps(detail) if not isinstance(detail, str) else detail
    except ValueError:
        text = resp.text
    return text[:300]


def _check(resp: httpx.Response, step: str) -> None:
    if resp.is_error:
        raise TranscriptionError(f"fal transcription failed while {step}: HTTP {resp.status_code}: {_error_detail(resp)}")


def _json(resp: httpx.Response, step: str) -> dict[str, Any]:
    _check(resp, step)
    try:
        body = resp.json()
    except ValueError as e:
        raise TranscriptionError(f"fal transcription failed while {step}: the response was not JSON") from e
    if not isinstance(body, dict):
        raise TranscriptionError(f"fal transcription failed while {step}: unexpected response")
    return body


def _fal_url(url: Any, fallback: str) -> str:
    """Only send the key to fal's own queue host: a URL from a response is used only if it is under FAL_QUEUE_URL."""
    return url if isinstance(url, str) and url.startswith(FAL_QUEUE_URL + "/") else fallback


def compact_audio(audio: Path, out_dir: Path) -> Path:
    """Re-encode to mono 16 kHz 48 kbit/s MP3 (~21 MB per hour) so long lectures fit one upload."""
    out = out_dir / f"{audio.stem}.mp3"
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", f"file:{audio.resolve()}", "-ac", "1", "-ar", "16000"]
    args += ["-c:a", "libmp3lame", "-b:a", "48k", str(out)]
    try:
        subprocess.run(args, capture_output=True, text=True, check=True, timeout=1800)  # noqa: S603
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise TranscriptionError("Could not compress the audio for upload to fal") from e
    return out


def _upload_file(audio: Path, tmp: Path) -> Path:
    """The file to upload: the audio itself, or a compressed copy in `tmp` if it is too big for one upload."""
    upload = compact_audio(audio, tmp) if audio.stat().st_size > FAL_SINGLE_UPLOAD_MAX_BYTES else audio
    if upload.stat().st_size > FAL_SINGLE_UPLOAD_MAX_BYTES:
        raise TranscriptionError("The audio is too long to upload to fal in one piece")
    return upload


async def fal_upload(audio: Path, http: httpx.AsyncClient, headers: Mapping[str, str]) -> str:
    """Upload to fal storage (initiate, then PUT the bytes) and return the file URL fal can read."""
    content_type = "audio/mpeg" if audio.suffix == ".mp3" else "audio/wav"
    init = _json(
        await http.post(
            FAL_STORAGE_URL,
            params={"storage_type": "fal-cdn-v3"},
            headers=headers,
            json={"content_type": content_type, "file_name": audio.name},
        ),
        "starting the audio upload",
    )
    upload_url, file_url = init.get("upload_url"), init.get("file_url")
    if not isinstance(upload_url, str) or not isinstance(file_url, str):
        raise TranscriptionError("fal transcription failed while starting the audio upload: no upload URL returned")
    # The upload URL is pre-signed: it must not get the API key.
    put = await http.put(upload_url, content=await asyncio.to_thread(audio.read_bytes), headers={"Content-Type": content_type})
    _check(put, "uploading the audio")
    return file_url


async def request_fal(
    audio: Path,
    api_key: str,
    vocabulary: Iterable[str] | None = None,
    client: httpx.AsyncClient | None = None,
    poll_s: float = FAL_POLL_S,
    timeout_s: float = FAL_TIMEOUT_S,
) -> dict[str, Any]:
    """Upload the audio, queue a fal-ai/whisper request, wait for it, and return the JSON result."""
    headers = {"Authorization": f"Key {api_key}"}
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=FAL_HTTP_TIMEOUT)
    deadline = time.monotonic() + timeout_s
    try:
        with tempfile.TemporaryDirectory() as tmp:
            upload = await asyncio.to_thread(_upload_file, audio, Path(tmp))
            audio_url = await fal_upload(upload, http, headers)

        submit = _json(
            await http.post(f"{FAL_QUEUE_URL}/{FAL_MODEL}", headers=headers, json=fal_input(audio_url, vocabulary)),
            "queueing the request",
        )
        request_id = submit.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise TranscriptionError("fal transcription failed while queueing the request: no request id returned")
        log.info("fal transcription queued: request %s", request_id)
        base = f"{FAL_QUEUE_URL}/{FAL_MODEL}/requests/{request_id}"
        status_url = _fal_url(submit.get("status_url"), f"{base}/status")
        response_url = _fal_url(submit.get("response_url"), base)

        while True:
            status = _json(await http.get(status_url, headers=headers), "waiting for the result")
            if status.get("error"):
                raise TranscriptionError(f"fal transcription failed: {str(status['error'])[:300]}")
            if status.get("status") == "COMPLETED":
                break
            if time.monotonic() > deadline:
                raise TranscriptionError(f"fal transcription timed out after {timeout_s:.0f} s (request {request_id})")
            await asyncio.sleep(poll_s)

        return _json(await http.get(response_url, headers=headers), "fetching the result")
    except httpx.TimeoutException as e:
        raise TranscriptionError("fal transcription timed out talking to fal") from e
    except httpx.HTTPError as e:
        raise TranscriptionError(f"fal transcription failed: network error ({type(e).__name__})") from e
    finally:
        if own_client:
            await http.aclose()


# ---------- Entry point ----------
def load_fake_transcript(path: Path = FAKE_TRANSCRIPT) -> list[TranscriptSegment]:
    return [TranscriptSegment.model_validate(s) for s in json.loads(path.read_text())]


def chosen_transcriber() -> TranscriberName:
    """TRANSCRIBER if set, else the fixture with fake models and ElevenLabs with live ones."""
    if settings.transcriber is not None:
        return settings.transcriber
    return "fixture" if settings.llm_mode == "fake" else "elevenlabs"


async def transcribe(audio: Path, vocabulary: list[str] | None = None, client: httpx.AsyncClient | None = None) -> list[TranscriptSegment]:
    """Pipeline stage (Transcriber): audio file -> transcript segments. `vocabulary` (board terms) primes fal Whisper."""
    match chosen_transcriber():
        case "fixture":
            return load_fake_transcript()
        case "fal":
            if not settings.fal_api_key:
                raise TranscriptionError("FAL_API_KEY (or FAL_KEY) is not set: cannot transcribe with fal (refusing to use the fixture)")
            return segments_from_fal(await request_fal(audio, settings.fal_api_key, vocabulary, client))
        case "elevenlabs":
            if not settings.elevenlabs_api_key:
                raise TranscriptionError("ELEVENLABS_API_KEY is not set: cannot transcribe in live mode (refusing to use the fixture)")
            return segments_from_response(await request_scribe(audio, settings.elevenlabs_api_key, client))
