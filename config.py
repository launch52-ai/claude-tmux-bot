from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "CTB_", "env_file": ".env", "env_file_encoding": "utf-8"}

    # Required
    bot_token: str
    chat_id: Optional[int] = None  # None triggers setup mode
    allowed_user_id: Optional[int] = None  # None allows any user during setup

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
    openai_api_key: Optional[str] = None

    # Paths
    projects_dir: Path = Path.home() / "Projects"
    state_file: Path = Path.home() / ".ctb" / "state.json"
    media_dir: Path = Path.home() / ".ctb" / "media"


settings = Settings()  # type: ignore[call-arg]
