"""V2 spec tests for C-1: transcription. Written from contracts + task acceptance only."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.config import REPO_ROOT, settings
from app.contracts.ai import TranscriptSegment
from app.pipeline import transcribe as T


def W(text, start, end, spk="speaker_0", typ="word"):
    return {"text": text, "start": start, "end": end, "type": typ, "speaker_id": spk}


def run(coro):
    return asyncio.run(coro)


def segs(words, **kw):
    return T.segments_from_response({"words": words}, **kw)


def test_fixture_response_groups_into_valid_segments():
    resp = json.loads((REPO_ROOT / "fixtures/elevenlabs/sample_response.json").read_text())
    out = T.segments_from_response(resp)
    assert out
    assert all(isinstance(s, TranscriptSegment) for s in out)
    assert "lecturer" in {s.speaker for s in out}
    for s in out:
        assert 0 <= s.start_s <= s.end_s
        assert s.text.strip()
    starts = [s.start_s for s in out]
    assert starts == sorted(starts)
    joined = " ".join(s.text for s in out)
    spoken = [w["text"] for w in resp["words"] if w["type"] == "word"]
    assert joined.split() == " ".join(spoken).split()


def test_main_speaker_is_lecturer_and_students_numbered():
    words = [W("hello", 0, 1, "a"), W("there", 1, 10, "a"), W("hi", 11, 12, "b"), W("ok", 20, 21, "c"), W("long", 22, 40, "a")]
    out = segs(words)
    by = {s.text.split()[0]: s.speaker for s in out}
    assert by["hello"] == "lecturer"
    assert by["hi"] == "student_1"
    assert by["ok"] == "student_2"


def test_lecturer_is_by_talk_time_not_first_speaker():
    out = segs([W("hm", 0, 0.5, "x"), W("lots", 1, 30, "y")])
    assert [s.speaker for s in out] == ["student_1", "lecturer"]


def test_speaker_change_splits():
    out = segs([W("a", 0, 1, "p"), W("b", 1, 2, "q"), W("c", 2, 3, "p")])
    assert len(out) == 3


def test_pause_splits():
    out = segs([W("a", 0, 1), W("b", 10, 11)])
    assert len(out) == 2


def test_no_segment_exceeds_max_length():
    words = [W(f"w{i}", i * 0.5, i * 0.5 + 0.5) for i in range(200)]
    out = segs(words)
    assert len(out) > 1
    assert all(s.end_s - s.start_s <= 15.0 + 1e-6 for s in out)
    assert sum(len(s.text.split()) for s in out) == 200


def test_custom_max_segment():
    words = [W(f"w{i}", i, i + 1) for i in range(20)]
    out = segs(words, max_segment_s=5.0)
    assert all(s.end_s - s.start_s <= 5.0 + 1e-6 for s in out)


def test_spacing_and_audio_events_dropped():
    out = segs([W("hi", 0, 1), W(" ", 1, 1.1, typ="spacing"), W("(laughter)", 1.1, 2, typ="audio_event"), W("there", 2, 3)])
    assert len(out) == 1 and out[0].text == "hi there"


def test_unordered_words_sorted():
    out = segs([W("second", 1, 2), W("first", 0, 1)])
    assert out[0].text == "first second"


def test_empty_inputs():
    assert T.segments_from_response({}) == []
    assert T.segments_from_response({"words": []}) == []
    assert T.segments_from_response({"words": None}) == []


def test_missing_speaker_id_and_missing_times_tolerated():
    out = segs([{"text": "a", "start": 0, "end": 1, "type": "word"}, {"text": "bad", "type": "word"}])
    assert len(out) == 1
    assert out[0].speaker == "lecturer"


def test_times_are_float_seconds():
    out = segs([W("a", 3725, 3726.5)])
    assert isinstance(out[0].start_s, float) and out[0].start_s == 3725
    assert out[0].end_s == 3726.5


def test_fake_mode_reads_fixture_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "llm_mode", "fake")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "KEY")

    def boom(*a, **k):
        raise AssertionError("network used in fake mode")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    out = run(T.transcribe(tmp_path / "nonexistent.wav"))
    expected = [TranscriptSegment.model_validate(s) for s in json.loads((REPO_ROOT / "fixtures/transcript.json").read_text())]
    assert out == expected
    assert "lecturer" in {s.speaker for s in out}


def test_live_no_key_raises_not_fixture(monkeypatch, tmp_path):
    # Changed from "falls back to fixture": review (V1/V3) found fabricated transcripts in live mode break citations.
    monkeypatch.setattr(settings, "llm_mode", "live")
    monkeypatch.setattr(settings, "elevenlabs_api_key", None)
    with pytest.raises(RuntimeError):
        run(T.transcribe(tmp_path / "x.wav"))


def test_live_mode_uses_mock_transport_and_sends_key(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "llm_mode", "live")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "SECRET")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF0000")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("xi-api-key")
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json={"words": [W("hello", 1, 2), W("world", 2, 3)]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await T.transcribe(audio, client=c)

    out = run(go())
    assert seen["key"] == "SECRET"
    assert "elevenlabs.io" in seen["url"]
    assert b"diarize" in seen["body"]
    assert out[0].text == "hello world"


def test_live_http_error_propagates(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "llm_mode", "live")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "K")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as c:
            return await T.transcribe(audio, client=c)

    with pytest.raises(httpx.HTTPStatusError):
        run(go())


def test_fake_transcript_has_no_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "llm_mode", "fake")
    out = run(T.transcribe(Path(tmp_path / "x.wav")))
    assert "xi-api-key" not in json.dumps([s.model_dump() for s in out])
