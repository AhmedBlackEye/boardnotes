import pytest

from app.llm.fake import FakeLLM
from app.pipeline import board


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board, "RETRY_BACKOFF_S", 0.0)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
