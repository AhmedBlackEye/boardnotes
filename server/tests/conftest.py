import pytest

from app.llm.fake import FakeLLM


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
