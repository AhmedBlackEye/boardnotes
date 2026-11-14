"""Offline stand-in for the model. Replays recorded responses so everything runs without API keys.

Lookup order for a request with task "board_read":
1. fixtures/llm/board_read/<key>.json, where key = request.untrusted.get("fixture_key") if present
2. fixtures/llm/board_read/default.json
Responses must validate against the requested schema, so fixtures double as contract examples.
"""

import json

from app.config import REPO_ROOT

from .client import LLMRequest, T, Usage

FIXTURE_DIR = REPO_ROOT / "fixtures" / "llm"


class MissingFixtureError(FileNotFoundError):
    pass


class FakeLLM:
    def __init__(self) -> None:
        self.usage = Usage()
        self.requests: list[LLMRequest] = []  # tests can inspect what was sent

    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        self.requests.append(req)
        self.usage.calls += 1
        folder = FIXTURE_DIR / req.task
        key = req.untrusted.get("fixture_key")
        for name in ([key] if key else []) + ["default"]:
            path = folder / f"{name}.json"
            if path.exists():
                return schema.model_validate(json.loads(path.read_text()))
        raise MissingFixtureError(f"No fixture for task '{req.task}' in {folder}")
