import secrets
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://boardnotes:boardnotes@localhost:5433/boardnotes"
    data_dir: Path = REPO_ROOT / "data"
    # Absolute origin of the web app; site-relative links (e.g. in PDFs) are resolved against it.
    public_base_url: str = "http://localhost:3000"
    # Browser origins allowed to call the API with cookies (comma-separated in .env: WEB_ORIGINS=https://a,https://b).
    web_origins: str = "http://localhost:3000"
    module_title: str = "Lecture notes"  # title on the cover of the all-lectures PDF
    session_secret: str = "dev-only-change-me"  # noqa: S105 - overridden by SESSION_SECRET outside local dev

    # "fake" replays recorded responses from fixtures/llm (no keys needed); "live" calls the real APIs.
    llm_mode: Literal["fake", "live"] = "fake"
    # "Ask the lecture" can use real model calls while the processing pipeline stays offline (each question costs
    # about 1-2 cents with Sonnet). Unset: follows LLM_MODE.
    ask_llm_mode: Literal["fake", "live"] | None = None
    ask_effort: Literal["low", "medium", "high"] = "medium"
    anthropic_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    # Speech-to-text: "fixture" replays fixtures/transcript.json, "fal" uses fal's hosted Whisper, "elevenlabs" uses
    # Scribe. Unset: "fixture" when LLM_MODE=fake, otherwise "elevenlabs".
    transcriber: Literal["fixture", "fal", "elevenlabs"] | None = None
    fal_api_key: str | None = Field(default=None, validation_alias=AliasChoices("fal_api_key", "fal_key"))

    model_glance: str = "claude-haiku-5-5"  # cheap per-frame read
    model_board: str = "claude-sonnet-5-5"  # fix checks, Q&A, term normalising
    model_read: str = "claude-opus-5-5"  # board reading and diagram redraws: accuracy here sets the quality of everything after
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

    @field_validator("transcriber", mode="before")
    @classmethod
    def _blank_transcriber_is_unset(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v


DEFAULT_SESSION_SECRET = "dev-only-change-me"  # noqa: S105


def check_production_settings(s: Settings) -> None:
    """Refuse to start with an empty or development cookie secret when real model calls are enabled or demo login is
    off (then the signed cookie is the only thing keeping students out of the lecturer routes).

    With demo login on and fake models anyone can already pick any user, so an empty secret is just replaced by a
    random one (sessions then end when the API restarts).
    """
    weak = s.session_secret in ("", DEFAULT_SESSION_SECRET)
    if weak and "live" in (s.llm_mode, s.ask_llm_mode):
        raise RuntimeError("Set SESSION_SECRET before running with LLM_MODE=live or ASK_LLM_MODE=live")
    if weak and not s.demo_login:
        raise RuntimeError("Set SESSION_SECRET before running with DEMO_LOGIN=false")
    if not s.session_secret:
        s.session_secret = secrets.token_urlsafe(32)


settings = Settings()
