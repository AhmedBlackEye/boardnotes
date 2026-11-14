from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://boardnotes:boardnotes@localhost:5433/boardnotes"
    data_dir: Path = REPO_ROOT / "data"
    session_secret: str = "dev-only-change-me"  # noqa: S105 - overridden by SESSION_SECRET outside local dev

    # "fake" replays recorded responses from fixtures/llm (no keys needed); "live" calls the real APIs.
    llm_mode: Literal["fake", "live"] = "fake"
    anthropic_api_key: str | None = None
    elevenlabs_api_key: str | None = None

    model_glance: str = "claude-haiku-5-5"  # cheap per-frame read
    model_board: str = "claude-sonnet-5-5"  # accurate board read, fix check, Q&A
    model_notes: str = "claude-opus-5-5"  # sections and notes

    max_upload_bytes: int = 4 * 1024**3
    frame_interval_s: float = 3.0


settings = Settings()
