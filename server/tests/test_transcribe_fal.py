"""fal Whisper transcription: response mapping, vocabulary prompt, request flow (all offline, fal is never called)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import REPO_ROOT, Settings
from app.pipeline import transcribe as tr

SAMPLE = REPO_ROOT / "fixtures" / "fal" / "sample_response.json"
KEY = "fal-secret-key-123"


def sample() -> dict[str, Any]:
    return json.loads(SAMPLE.read_text())


def chunk(text: str, start: float | None, end: float | None, speaker: str | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {"timestamp": [start, end], "text": f" {text}"}
    if speaker:
        c["speaker"] = speaker
    return c


# ---------- Mapping ----------
def test_sample_maps_to_segments_with_lecturer_and_students() -> None:
    segments = tr.segments_from_fal(sample())
    assert [s.speaker for s in segments] == ["lecturer"] * 4 + ["student_1", "lecturer", "student_2", "lecturer"]
    assert segments[0].text.startswith("Today we want to solve this system:")
    assert segments[4].text == "Can we also eliminate x first?"
    assert all(s.end_s - s.start_s <= tr.MAX_SEGMENT_S for s in segments)
    assert all(a.end_s <= b.start_s for a, b in zip(segments, segments[1:], strict=False))
    assert all(s.end_s >= s.start_s for s in segments)


def test_sample_keeps_every_word() -> None:
    segments = tr.segments_from_fal(sample(), max_segment_s=5.0)
    assert all(s.end_s - s.start_s <= 5.0 for s in segments)
    assert " ".join(s.text for s in segments).split() == [c["text"].strip() for c in sample()["chunks"]]


def test_matches_scribe_mapping_for_same_audio() -> None:
    """The fal fixture is the same demo opening as the ElevenLabs one, so both providers give the same segments."""
    scribe = json.loads((REPO_ROOT / "fixtures" / "elevenlabs" / "sample_response.json").read_text())
    fal = tr.segments_from_fal(sample())
    el = tr.segments_from_response(scribe)
    assert [(s.speaker, s.text) for s in fal] == [(s.speaker, s.text) for s in el]


def test_no_diarization_everyone_is_lecturer() -> None:
    resp = {"chunks": [chunk("Hello", 0.0, 0.4), chunk("there.", 0.5, 0.9), chunk("Question?", 3.0, 3.5)]}
    segments = tr.segments_from_fal(resp)
    assert [s.speaker for s in segments] == ["lecturer", "lecturer"]
    assert [s.text for s in segments] == ["Hello there.", "Question?"]


def test_speaker_from_diarization_segments_when_chunks_lack_it() -> None:
    resp = {
        "chunks": [chunk("Long", 0.0, 2.0), chunk("answer.", 2.0, 5.0), chunk("Why?", 5.2, 5.6), chunk("Because.", 6.0, 7.0)],
        "diarization_segments": [
            {"timestamp": [0.0, 5.1], "speaker": "SPEAKER_00"},
            {"timestamp": [5.1, 5.8], "speaker": "SPEAKER_01"},
            {"timestamp": [5.9, 7.0], "speaker": "SPEAKER_00"},
        ],
    }
    segments = tr.segments_from_fal(resp)
    assert [(s.speaker, s.text) for s in segments] == [("lecturer", "Long answer."), ("student_1", "Why?"), ("lecturer", "Because.")]


def test_open_end_timestamps_and_bad_chunks() -> None:
    resp = {
        "chunks": [
            chunk("b", 1.0, None),
            chunk("a", 0.0, 0.5),
            chunk("c", 1.4, None),
            {"timestamp": [None, 2.0], "text": "dropped"},
            {"timestamp": "junk", "text": "dropped"},
            chunk("   ", 2.0, 2.1),
        ]
    }
    segments = tr.segments_from_fal(resp)
    assert len(segments) == 1
    s = segments[0]
    assert s.text == "a b c" and s.start_s == 0.0 and s.end_s == 1.4  # "b" ends where "c" starts; "c" at its start


def test_missing_speaker_inherits_previous() -> None:
    resp = {"chunks": [chunk("Hi", 0.0, 0.3, "SPEAKER_01"), chunk("all", 0.3, 0.6)]}
    assert [s.speaker for s in tr.segments_from_fal(resp)] == ["lecturer"]


def test_empty_responses() -> None:
    assert tr.segments_from_fal({}) == []
    assert tr.segments_from_fal({"chunks": None, "diarization_segments": None}) == []


# ---------- Vocabulary prompt ----------
def test_vocabulary_prompt_dedupes_and_caps() -> None:
    assert tr.vocabulary_prompt(None) == ""
    assert tr.vocabulary_prompt(["Eigenvalue", "  eigenvalue ", "", "row  picture", "x" * 100, "Gauss"]) == "Eigenvalue, row picture, Gauss"
    many = [f"term{i}" for i in range(200)]
    assert len(tr.vocabulary_prompt(many).split(", ")) == tr.VOCAB_MAX_TERMS
    long_terms = [f"{i:02d}" + "y" * 50 for i in range(30)]
    assert len(tr.vocabulary_prompt(long_terms)) <= tr.VOCAB_MAX_CHARS


def test_fal_input_carries_prompt_only_when_present() -> None:
    body = tr.fal_input("https://v3.fal.media/files/a.wav", ["Gaussian elimination"])
    assert body == {
        "audio_url": "https://v3.fal.media/files/a.wav",
        "task": "transcribe",
        "chunk_level": "word",
        "diarize": True,
        "prompt": "Gaussian elimination",
    }
    assert "prompt" not in tr.fal_input("u", [])


# ---------- Settings ----------
def test_settings_accept_fal_key_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAL_API_KEY", raising=False)
    monkeypatch.setenv("FAL_KEY", "a")
    monkeypatch.setenv("TRANSCRIBER", "fal")
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.fal_api_key == "a" and s.transcriber == "fal"
    monkeypatch.setenv("FAL_API_KEY", "b")
    monkeypatch.setenv("TRANSCRIBER", " ")
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.fal_api_key == "b" and s.transcriber is None


def test_choice_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr.settings, "transcriber", None)
    monkeypatch.setattr(tr.settings, "llm_mode", "fake")
    assert tr.chosen_transcriber() == "fixture"
    monkeypatch.setattr(tr.settings, "llm_mode", "live")
    assert tr.chosen_transcriber() == "elevenlabs"
    monkeypatch.setattr(tr.settings, "transcriber", "fal")
    assert tr.chosen_transcriber() == "fal"


async def test_explicit_fixture_in_live_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr.settings, "llm_mode", "live")
    monkeypatch.setattr(tr.settings, "transcriber", "fixture")
    assert await tr.transcribe(tmp_path / "missing.wav", ["x"]) == tr.load_fake_transcript()


# ---------- Request flow (mock transport) ----------
class FakeFal:
    """Imitates fal storage + queue. Records every request."""

    def __init__(self, polls_before_done: int = 1, result: dict[str, Any] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.polls_left = polls_before_done
        self.result = result if result is not None else sample()
        self.status_error: str | None = None
        self.submit_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(tr.FAL_STORAGE_URL):
            return httpx.Response(
                200, json={"upload_url": "https://upload.example/signed?sig=1", "file_url": "https://v3.fal.media/files/audio.wav"}
            )
        if url.startswith("https://upload.example/"):
            return httpx.Response(200)
        base = f"{tr.FAL_QUEUE_URL}/{tr.FAL_MODEL}"
        if request.method == "POST" and url == base:
            if self.submit_status != 200:
                return httpx.Response(self.submit_status, json={"detail": "Invalid key"})
            return httpx.Response(
                200,
                json={"request_id": "req-1", "status_url": f"{base}/requests/req-1/status", "response_url": f"{base}/requests/req-1"},
            )
        if url == f"{base}/requests/req-1/status":
            if self.status_error:
                return httpx.Response(200, json={"status": "COMPLETED", "error": self.status_error})
            if self.polls_left > 0:
                self.polls_left -= 1
                return httpx.Response(202, json={"status": "IN_PROGRESS"})
            return httpx.Response(200, json={"status": "COMPLETED"})
        if url == f"{base}/requests/req-1":
            return httpx.Response(200, json=self.result)
        return httpx.Response(404)


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    p = tmp_path / "audio.wav"
    p.write_bytes(b"RIFF....WAVE")
    return p


@pytest.fixture
def live_fal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr.settings, "llm_mode", "live")
    monkeypatch.setattr(tr.settings, "transcriber", "fal")
    monkeypatch.setattr(tr.settings, "fal_api_key", KEY)
    monkeypatch.setattr(tr, "FAL_POLL_S", 0.0)


async def run_fal(fake: FakeFal, audio: Path, vocabulary: list[str] | None = None) -> list[Any]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        return await tr.transcribe(audio, vocabulary, client=client)


@pytest.mark.usefixtures("live_fal")
async def test_fal_flow_uploads_queues_polls_and_maps(audio: Path) -> None:
    fake = FakeFal(polls_before_done=2)
    segments = await run_fal(fake, audio, ["Gaussian elimination", "row picture", "gaussian elimination"])
    assert segments == tr.segments_from_fal(sample())

    init, put, submit, *polls, result = fake.requests
    assert init.headers["Authorization"] == f"Key {KEY}"
    assert json.loads(init.content) == {"content_type": "audio/wav", "file_name": "audio.wav"}
    assert put.method == "PUT" and put.content == audio.read_bytes()
    assert "Authorization" not in put.headers  # the pre-signed upload URL never sees the key
    body = json.loads(submit.content)
    assert body["audio_url"] == "https://v3.fal.media/files/audio.wav"
    assert body["prompt"] == "Gaussian elimination, row picture"
    assert body["diarize"] is True and body["chunk_level"] == "word"
    assert len(polls) == 3 and all(p.headers["Authorization"] == f"Key {KEY}" for p in polls)
    assert result.method == "GET"


@pytest.mark.usefixtures("live_fal")
async def test_fal_key_missing_raises(audio: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr.settings, "fal_api_key", None)
    with pytest.raises(tr.TranscriptionError, match="FAL_API_KEY"):
        await run_fal(FakeFal(), audio)


@pytest.mark.usefixtures("live_fal")
async def test_fal_http_error_is_clear_and_hides_key(audio: Path) -> None:
    fake = FakeFal()
    fake.submit_status = 401
    with pytest.raises(tr.TranscriptionError) as e:
        await run_fal(fake, audio)
    assert "queueing the request" in str(e.value) and "401" in str(e.value) and "Invalid key" in str(e.value)
    assert KEY not in str(e.value)


@pytest.mark.usefixtures("live_fal")
async def test_fal_job_error(audio: Path) -> None:
    fake = FakeFal()
    fake.status_error = "Audio could not be decoded"
    with pytest.raises(tr.TranscriptionError, match="could not be decoded"):
        await run_fal(fake, audio)


@pytest.mark.usefixtures("live_fal")
async def test_fal_times_out(audio: Path) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(FakeFal(polls_before_done=10**6))) as client:
        with pytest.raises(tr.TranscriptionError, match="timed out"):
            await tr.request_fal(audio, KEY, None, client, poll_s=0.0, timeout_s=0.0)


@pytest.mark.usefixtures("live_fal")
async def test_fal_network_timeout(audio: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        with pytest.raises(tr.TranscriptionError, match="timed out") as e:
            await tr.transcribe(audio, client=client)
    assert KEY not in str(e.value)


@pytest.mark.usefixtures("live_fal")
async def test_fal_ignores_foreign_status_urls(audio: Path) -> None:
    """A status/response URL outside fal's queue host never receives the key."""
    fake = FakeFal(polls_before_done=0)
    inner = fake.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        resp = inner(request)
        if request.method == "POST" and str(request.url) == f"{tr.FAL_QUEUE_URL}/{tr.FAL_MODEL}":
            return httpx.Response(
                200, json={"request_id": "req-1", "status_url": "https://evil.example/s", "response_url": "https://evil.example/r"}
            )
        return resp

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await tr.transcribe(audio, client=client)
    assert not any("evil.example" in str(r.url) for r in fake.requests)


@pytest.mark.usefixtures("live_fal")
async def test_large_audio_is_compacted_before_upload(audio: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compacted: list[Path] = []

    def fake_compact(src: Path, out_dir: Path) -> Path:
        out = out_dir / "audio.mp3"
        out.write_bytes(b"ID3")
        compacted.append(src)
        return out

    monkeypatch.setattr(tr, "FAL_SINGLE_UPLOAD_MAX_BYTES", 5)
    monkeypatch.setattr(tr, "compact_audio", fake_compact)
    fake = FakeFal(polls_before_done=0)
    await run_fal(fake, audio)
    assert compacted == [audio]
    assert json.loads(fake.requests[0].content) == {"content_type": "audio/mpeg", "file_name": "audio.mp3"}
