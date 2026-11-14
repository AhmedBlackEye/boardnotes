"""Stage: transcribe the lecture audio with ElevenLabs Scribe (word timestamps + speaker diarization).

`transcribe(audio)` is the pipeline entry point. In fake mode, or when no ELEVENLABS_API_KEY is set, it
returns the recorded transcript from fixtures/transcript.json so the pipeline runs offline.

The response-to-segments logic lives in the pure function `segments_from_response`.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import REPO_ROOT, settings
from app.contracts.ai import TranscriptSegment

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
SCRIBE_MODEL = "scribe_v2"
FAKE_TRANSCRIPT = REPO_ROOT / "fixtures" / "transcript.json"

MAX_SEGMENT_S = 15.0  # hard cap on a segment's length
PAUSE_SPLIT_S = 1.5  # a silence this long always starts a new segment
SENTENCE_SPLIT_AFTER_S = 8.0  # once a segment is this long, end it at the next sentence end
SENTENCE_ENDINGS = (".", "?", "!")
UNKNOWN_SPEAKER = "unknown"


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float
    speaker: str


def _words(response: Mapping[str, Any]) -> list[_Word]:
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


def segments_from_response(
    response: Mapping[str, Any],
    max_segment_s: float = MAX_SEGMENT_S,
    pause_split_s: float = PAUSE_SPLIT_S,
) -> list[TranscriptSegment]:
    """Group Scribe words into segments of at most ~max_segment_s seconds.

    A new segment starts when the speaker changes, after a pause of pause_split_s or more, at a sentence end once
    the segment is reasonably long, or when adding the next word would exceed max_segment_s.
    """
    words = _words(response)
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


def load_fake_transcript(path: Path = FAKE_TRANSCRIPT) -> list[TranscriptSegment]:
    return [TranscriptSegment.model_validate(s) for s in json.loads(path.read_text())]


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


async def transcribe(audio: Path, client: httpx.AsyncClient | None = None) -> list[TranscriptSegment]:
    """Pipeline stage (Transcriber): audio file -> transcript segments."""
    if settings.llm_mode == "fake" or not settings.elevenlabs_api_key:
        return load_fake_transcript()
    response = await request_scribe(audio, settings.elevenlabs_api_key, client)
    return segments_from_response(response)
