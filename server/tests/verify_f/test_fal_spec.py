"""V2 tests for workstream F (Q-1): fal Whisper transcription, written from the spec only. Fully offline."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.contracts.ai import TranscriptSegment
from app.pipeline import transcribe as tr

KEY = "fal-V2-secret-key"
QUEUE = "https://queue.fal.run"


def ch(text: str, s: float | None, e: float | None, spk: str | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {"timestamp": [s, e], "text": f" {text}"}
    if spk:
        c["speaker"] = spk
    return c


# ---------- settings / provider choice ----------
def test_settings_transcriber_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("TRANSCRIBER", "FAL_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(var, raising=False)
    for name in ("fal", "elevenlabs", "fixture"):
        monkeypatch.setenv("TRANSCRIBER", name)
        assert Settings(_env_file=None).transcriber == name
    monkeypatch.setenv("TRANSCRIBER", "")
    assert Settings(_env_file=None).transcriber is None
    monkeypatch.setenv("TRANSCRIBER", "bogus")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_fal_key_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setenv("FAL_API_KEY", "abc")
    assert Settings(_env_file=None).fal_api_key == "abc"


def test_default_provider_follows_llm_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr.settings, "transcriber", None)
    monkeypatch.setattr(tr.settings, "llm_mode", "fake")
    assert tr.chosen_transcriber() == "fixture"
    monkeypatch.setattr(tr.settings, "llm_mode", "live")
    assert tr.chosen_transcriber() == "elevenlabs"
    monkeypatch.setattr(tr.settings, "transcriber", "fal")
    assert tr.chosen_transcriber() == "fal"


async def test_fixture_provider_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr.settings, "transcriber", "fixture")
    monkeypatch.setattr(tr.settings, "fal_api_key", None)
    segs = await tr.transcribe(Path("/nonexistent.wav"), ["x"])
    assert segs and all(isinstance(s, TranscriptSegment) for s in segs)


async def test_fal_without_key_raises_not_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr.settings, "transcriber", "fal")
    monkeypatch.setattr(tr.settings, "fal_api_key", None)
    with pytest.raises(tr.TranscriptionError):
        await tr.transcribe(Path("/nonexistent.wav"))


# ---------- vocabulary prompt ----------
def test_prompt_empty_and_none() -> None:
    assert tr.vocabulary_prompt(None) == ""
    assert tr.vocabulary_prompt([]) == ""
    assert tr.vocabulary_prompt(["", "   "]) == ""


def test_prompt_dedupes_normalises_keeps_order() -> None:
    p = tr.vocabulary_prompt(["Fourier  transform", "eigenvalue", "fourier transform", "  Eigenvalue ", "Laplace"])
    assert p == "Fourier transform, eigenvalue, Laplace"


def test_prompt_is_bounded() -> None:
    p = tr.vocabulary_prompt([f"term{i}" for i in range(1000)])
    assert 0 < len(p) <= tr.VOCAB_MAX_CHARS
    assert len(p.split(", ")) <= tr.VOCAB_MAX_TERMS
    assert tr.vocabulary_prompt(["x" * 500, "ok"]) == "ok"


def test_prompt_accepts_generator() -> None:
    assert tr.vocabulary_prompt(t for t in ["a", "b"]) == "a, b"


def test_fal_input_shape() -> None:
    body = tr.fal_input("https://cdn/x.wav", ["Jacobian"])
    assert body["audio_url"] == "https://cdn/x.wav"
    assert body["prompt"] == "Jacobian"
    assert body["chunk_level"] == "word"
    assert "prompt" not in tr.fal_input("https://cdn/x.wav", [])
    assert "prompt" not in tr.fal_input("https://cdn/x.wav", None)


# ---------- mapping ----------
def test_times_are_float_seconds_and_valid_contract() -> None:
    segs = tr.segments_from_fal({"chunks": [ch("Hi", 0, 1), ch("there.", 1, 2)]})
    assert len(segs) == 1
    assert isinstance(segs[0].start_s, float) and segs[0].start_s == 0.0 and segs[0].end_s == 2.0
    TranscriptSegment.model_validate(segs[0].model_dump())


def test_empty_and_missing_chunks() -> None:
    assert tr.segments_from_fal({}) == []
    assert tr.segments_from_fal({"chunks": []}) == []
    assert tr.segments_from_fal({"chunks": None}) == []


def test_negative_start_clamped_and_end_not_before_start() -> None:
    segs = tr.segments_from_fal({"chunks": [ch("a", -1.0, 0.5), ch("b", 2.0, 1.0)]})
    assert all(s.start_s >= 0 and s.end_s >= s.start_s for s in segs)


def test_unsorted_chunks_ordered() -> None:
    segs = tr.segments_from_fal({"chunks": [ch("world", 1.0, 1.5), ch("hello", 0.0, 0.5)]})
    assert segs[0].text == "hello world"


def test_long_speech_split_under_cap() -> None:
    chunks = [ch(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(200)]
    segs = tr.segments_from_fal({"chunks": chunks})
    assert len(segs) > 1
    assert all(s.end_s - s.start_s <= tr.MAX_SEGMENT_S for s in segs)
    assert " ".join(s.text for s in segs).split() == [f"w{i}" for i in range(200)]


def test_pause_splits() -> None:
    segs = tr.segments_from_fal({"chunks": [ch("a", 0, 0.5), ch("b", 5, 5.5)]})
    assert len(segs) == 2


def test_most_talkative_is_lecturer_students_numbered_by_appearance() -> None:
    chunks = [ch("q", 0, 0.5, "B"), ch("long", 1, 6, "A"), ch("q2", 7, 7.5, "C"), ch("more", 8, 14, "A")]
    segs = tr.segments_from_fal({"chunks": chunks})
    assert [s.speaker for s in segs] == ["student_1", "lecturer", "student_2", "lecturer"]


def test_speaker_change_splits_segment() -> None:
    segs = tr.segments_from_fal({"chunks": [ch("a", 0, 1, "A"), ch("b", 1, 2, "B")]})
    assert len(segs) == 2


def test_malformed_chunks_do_not_crash() -> None:
    resp = {
        "chunks": [
            {"text": "no ts"},
            {"timestamp": [0.0], "text": "short"},
            {"timestamp": ["x", "y"], "text": "bad"},
            {"timestamp": [0.0, 1.0], "text": "   "},
            ch("ok", 0.0, 1.0),
        ]
    }
    segs = tr.segments_from_fal(resp)
    assert "ok" in " ".join(s.text for s in segs)


# ---------- request flow (mock transport) ----------
class Fal:
    def __init__(
        self,
        result: dict[str, Any] | None = None,
        statuses: list[dict[str, Any]] | None = None,
        submit_extra: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[httpx.Request] = []
        self.result = result or {"chunks": [ch("Hello", 0.0, 0.5)]}
        self.statuses = statuses or [{"status": "COMPLETED"}]
        self.submit_extra = submit_extra or {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        u = str(req.url)
        if u.startswith("https://rest.fal.ai/storage"):
            return httpx.Response(200, json={"upload_url": "https://upload.example/put", "file_url": "https://cdn.example/a.wav"})
        if req.method == "PUT":
            return httpx.Response(200)
        if req.method == "POST" and u == f"{QUEUE}/fal-ai/whisper":
            return httpx.Response(200, json={"request_id": "rid1", **self.submit_extra})
        if u.endswith("/status"):
            return httpx.Response(200, json=self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])
        if u == f"{QUEUE}/fal-ai/whisper/requests/rid1":
            return httpx.Response(200, json=self.result)
        return httpx.Response(404, json={"detail": "nope"})


def client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def wav(tmp_path: Path) -> Path:
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF....WAVE")
    return p


def _submit(fal: Fal) -> httpx.Request:
    return next(r for r in fal.calls if r.method == "POST" and r.url.host == "queue.fal.run")


async def test_happy_path_sends_prompt_and_key_only_to_fal(wav: Path) -> None:
    fal = Fal(statuses=[{"status": "IN_QUEUE"}, {"status": "IN_PROGRESS"}, {"status": "COMPLETED"}])
    async with client(fal) as c:
        out = await tr.request_fal(wav, KEY, ["Jacobian", "eigenvalue"], c, poll_s=0.0)
    assert out == fal.result
    submit = _submit(fal)
    assert json.loads(submit.content)["prompt"] == "Jacobian, eigenvalue"
    assert submit.headers["authorization"] == f"Key {KEY}"
    put = next(r for r in fal.calls if r.method == "PUT")
    assert "authorization" not in put.headers  # pre-signed URL gets no key
    for r in fal.calls:
        if r.url.host not in ("queue.fal.run", "rest.fal.ai"):
            assert "authorization" not in r.headers


async def test_vocabulary_text_stays_in_prompt_field(wav: Path) -> None:
    fal = Fal()
    async with client(fal) as c:
        await tr.request_fal(wav, KEY, ["ignore previous instructions", "x"], c, poll_s=0.0)
    body = json.loads(_submit(fal).content)
    assert set(body) <= {"audio_url", "task", "chunk_level", "diarize", "prompt", "language", "version"}


async def test_foreign_status_url_does_not_get_key(wav: Path) -> None:
    fal = Fal(submit_extra={"status_url": "https://evil.example/status", "response_url": "https://evil.example/r"})
    async with client(fal) as c:
        out = await tr.request_fal(wav, KEY, None, c, poll_s=0.0)
    assert out == fal.result
    assert not any(r.url.host == "evil.example" for r in fal.calls)


async def test_http_error_message_has_no_key(wav: Path) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorized"})

    async with client(h) as c:
        with pytest.raises(tr.TranscriptionError) as e:
            await tr.request_fal(wav, KEY, None, c, poll_s=0.0)
    assert KEY not in str(e.value)
    assert "401" in str(e.value)


async def test_failed_status_raises(wav: Path) -> None:
    fal = Fal(statuses=[{"status": "IN_PROGRESS", "error": "boom"}])
    async with client(fal) as c:
        with pytest.raises(tr.TranscriptionError):
            await tr.request_fal(wav, KEY, None, c, poll_s=0.0)


async def test_timeout_raises(wav: Path) -> None:
    fal = Fal(statuses=[{"status": "IN_PROGRESS"}])
    async with client(fal) as c:
        with pytest.raises(tr.TranscriptionError, match="timed out"):
            await tr.request_fal(wav, KEY, None, c, poll_s=0.0, timeout_s=0.05)


async def test_network_error_wrapped_without_key(wav: Path) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect {KEY}")

    async with client(h) as c:
        with pytest.raises(tr.TranscriptionError) as e:
            await tr.request_fal(wav, KEY, None, c)
    assert KEY not in str(e.value)


async def test_missing_request_id(wav: Path) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        if req.url.host == "rest.fal.ai":
            return httpx.Response(200, json={"upload_url": "https://u.example/x", "file_url": "https://c.example/x"})
        if req.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(200, json={})

    async with client(h) as c:
        with pytest.raises(tr.TranscriptionError):
            await tr.request_fal(wav, KEY, None, c, poll_s=0.0)


async def test_transcribe_end_to_end_fal(monkeypatch: pytest.MonkeyPatch, wav: Path) -> None:
    monkeypatch.setattr(tr.settings, "transcriber", "fal")
    monkeypatch.setattr(tr.settings, "fal_api_key", KEY)
    fal = Fal(result={"chunks": [ch("Hello", 0.0, 0.5), ch("class.", 0.6, 1.0)]})
    async with client(fal) as c:
        segs = await tr.transcribe(wav, ["Hamiltonian"], client=c)
    assert [(s.speaker, s.text, s.start_s, s.end_s) for s in segs] == [("lecturer", "Hello class.", 0.0, 1.0)]
    assert json.loads(_submit(fal).content)["prompt"] == "Hamiltonian"


async def test_oversize_audio_without_ffmpeg_fails_cleanly(monkeypatch: pytest.MonkeyPatch, wav: Path) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(tr, "FAL_SINGLE_UPLOAD_MAX_BYTES", 4)
    monkeypatch.setattr(tr.subprocess, "run", boom)
    async with client(Fal()) as c:
        with pytest.raises(tr.TranscriptionError):
            await tr.request_fal(wav, KEY, None, c, poll_s=0.0)
