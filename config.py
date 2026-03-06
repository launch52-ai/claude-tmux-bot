from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "CTB_"}

    # Required
    bot_token: str
    chat_id: int
    allowed_user_id: int

    # Topic mode
    topic_mode: str = "session"  # "session" or "window"

    # Polling / streaming
    poll_interval_active: float = 0.5
    poll_interval_idle: float = 2.0
    output_debounce: float = 1.5
    text_line_limit: int = 30

    # Sleep prevention
    caffeinate: bool = True

    # Optional integrations
    openai_api_key: str | None = None

    # Paths
    projects_dir: Path = Path.home() / "Projects"
    state_file: Path = Path.home() / ".ctb" / "state.json"
    media_dir: Path = Path.home() / ".ctb" / "media"


settings = Settings()  # type: ignore[call-arg]
