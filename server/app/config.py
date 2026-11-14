from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://boardnotes:boardnotes@localhost:5433/boardnotes"
    data_dir: Path = REPO_ROOT / "data"
    # Absolute origin of the web app; site-relative links (e.g. in PDFs) are resolved against it.
    public_base_url: str = "http://localhost:3000"
    session_secret: str = "dev-only-change-me"  # noqa: S105 - overridden by SESSION_SECRET outside local dev

    # "fake" replays recorded responses from fixtures/llm (no keys needed); "live" calls the real APIs.
    llm_mode: Literal["fake", "live"] = "fake"
    anthropic_api_key: str | None = None
    elevenlabs_api_key: str | None = None

    model_glance: str = "claude-haiku-5-5"  # cheap per-frame read
    model_board: str = "claude-sonnet-5-5"  # accurate board read, fix check, Q&A
    model_notes: str = "claude-opus-5-5"  # sections and notes

    # Demo login lets anyone pick a seeded user (lecturer included); turn it off for anything public.
    demo_login: bool = True
    cookie_secure: bool | None = None  # None: Secure only when the request came in over https

    ask_per_minute: int = 10  # per student, across lectures
    ask_per_lecture_per_day: int = 100  # per student and lecture
    llm_concurrency: int = 4  # interactive model calls (fix checks, questions) running at once
    progress_stream_max_s: float = 3 * 3600  # an SSE progress stream ends after this long

    max_upload_bytes: int = 4 * 1024**3
    frame_interval_s: float = 3.0
    max_duration_s: float = 4 * 3600  # longer recordings are rejected at upload
    max_frames: int = 5000  # cap on frames sampled (and glanced at) per video


DEFAULT_SESSION_SECRET = "dev-only-change-me"  # noqa: S105


def check_production_settings(s: Settings) -> None:
    """Refuse to start with the development cookie secret when real model calls are enabled."""
    if s.llm_mode == "live" and s.session_secret in ("", DEFAULT_SESSION_SECRET):
        raise RuntimeError("Set SESSION_SECRET before running with LLM_MODE=live")


settings = Settings()
