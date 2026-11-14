import json
from pathlib import Path

import httpx
import pytest

from app.config import REPO_ROOT
from app.pipeline import transcribe as tr

SAMPLE = REPO_ROOT / "fixtures" / "elevenlabs" / "sample_response.json"


def sample() -> dict:
    return json.loads(SAMPLE.read_text())


def word(text: str, start: float, end: float, speaker: str | None = "speaker_0", type_: str = "word") -> dict:
    return {"text": text, "start": start, "end": end, "type": type_, "speaker_id": speaker, "logprob": 0.0}


def test_sample_response_groups_into_segments() -> None:
    segments = tr.segments_from_response(sample())
    assert [s.speaker for s in segments] == [
        "lecturer",
        "lecturer",
        "lecturer",
        "lecturer",
        "student_1",
        "lecturer",
        "student_2",
        "lecturer",
    ]
    assert segments[0].text.startswith("Today we want to solve this system:")
    assert segments[4].text == "Can we also eliminate x first?"
    assert all(s.end_s - s.start_s <= tr.MAX_SEGMENT_S for s in segments)
    assert all(a.end_s <= b.start_s for a, b in zip(segments, segments[1:], strict=False))
    # Audio events and spacing tokens never reach the text.
    assert not any("chalk" in s.text or "  " in s.text for s in segments)


def test_segments_respect_max_length() -> None:
    segments = tr.segments_from_response(sample(), max_segment_s=5.0)
    assert len(segments) > 8
    assert all(s.end_s - s.start_s <= 5.0 for s in segments)
    # No words are lost when splitting.
    joined = " ".join(s.text for s in segments)
    assert joined.split() == [w["text"] for w in sample()["words"] if w["type"] == "word"]


def test_long_pause_starts_new_segment() -> None:
    resp = {"words": [word("one", 0.0, 0.5), word("two", 0.6, 1.0), word("three", 3.0, 3.4)]}
    segments = tr.segments_from_response(resp)
    assert [s.text for s in segments] == ["one two", "three"]
    assert segments[1].start_s == 3.0


def test_most_speech_is_lecturer_even_if_not_first() -> None:
    resp = {
        "words": [
            word("Question?", 0.0, 0.5, "speaker_3"),
            word("Long", 1.0, 3.0, "speaker_9"),
            word("answer.", 3.0, 6.0, "speaker_9"),
            word("Thanks", 7.0, 7.5, "speaker_5"),
        ]
    }
    segments = tr.segments_from_response(resp)
    assert [s.speaker for s in segments] == ["student_1", "lecturer", "student_2"]


def test_missing_speaker_and_timestamps() -> None:
    resp = {"words": [word("hi", 0.0, 0.2, None), {"text": "x", "type": "word", "logprob": 0.0, "start": None, "end": None}]}
    segments = tr.segments_from_response(resp)
    assert len(segments) == 1 and segments[0].speaker == "lecturer"


def test_empty_response() -> None:
    assert tr.segments_from_response({"words": []}) == []


async def test_fake_mode_uses_fixture_transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr.settings, "llm_mode", "fake")
    segments = await tr.transcribe(tmp_path / "missing.wav")
    assert segments == tr.load_fake_transcript()
    assert segments[0].speaker == "lecturer"


async def test_live_mode_calls_scribe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF....WAVE")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("xi-api-key")
        seen["body"] = request.content
        return httpx.Response(200, json=sample())

    monkeypatch.setattr(tr.settings, "llm_mode", "live")
    monkeypatch.setattr(tr.settings, "elevenlabs_api_key", "test-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        segments = await tr.transcribe(audio, client=client)

    assert seen["url"] == tr.ELEVENLABS_STT_URL
    assert seen["key"] == "test-key"
    for field in (b'name="model_id"', b"scribe_v2", b'name="diarize"', b'name="timestamps_granularity"', b'name="file"'):
        assert field in seen["body"]
    assert segments == tr.segments_from_response(sample())


async def test_live_mode_raises_on_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(tr.settings, "llm_mode", "live")
    monkeypatch.setattr(tr.settings, "elevenlabs_api_key", "test-key")
    transport = httpx.MockTransport(lambda _: httpx.Response(401, json={"detail": "bad key"}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await tr.transcribe(audio, client=client)
