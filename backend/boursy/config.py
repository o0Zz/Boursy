"""Application settings, read from environment variables (prefix BOURSY_) and the repo-level .env file."""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ENV = _PACKAGE_DIR.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOURSY_", env_file=(_REPO_ENV, ".env"), extra="ignore")

    data_dir: Path = Path("./data")
    app_password: str = ""
    session_secret: str = ""
    cookie_secure: bool = False
    timezone: str = "Europe/Paris"
    scheduler_enabled: bool = True
    static_dir: Path = _PACKAGE_DIR.parent / "static"
    history_years: int = 6  # 5 years of backtest after the 200-day warm-up
    full_refresh_days: int = 7
    log_level: str = "INFO"
    # Link used in notifications, e.g. https://boursy.example.org
    public_url: str = ""

    # Push notifications (ntfy)
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""
    # Email (SMTP)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    mail_to: str = ""

    # Claude. The API key is read from ANTHROPIC_API_KEY too; the subscription token comes from
    # `claude setup-token`.
    anthropic_api_key: str = Field(
        "", validation_alias=AliasChoices("BOURSY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    claude_code_oauth_token: str = Field(
        "", validation_alias=AliasChoices("BOURSY_CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    )
    claude_bin: str = "claude"
    claude_timeout_s: int = 600

    @property
    def db_path(self) -> Path:
        return self.data_dir / "boursy.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    def resolved_session_secret(self) -> str:
        """Session secret from the environment, or a random one persisted in the data directory."""
        if self.session_secret:
            return self.session_secret
        path = self.data_dir / "session.key"
        if path.exists():
            return path.read_text().strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(48)
        path.write_text(value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
