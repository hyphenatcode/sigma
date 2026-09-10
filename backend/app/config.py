"""Application settings, read from the environment (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Sigma"
    environment: str = "development"
    debug: bool = True

    # PostgreSQL (§7). SQLite is allowed only for local test runs.
    database_url: str = "postgresql+psycopg2://sigma:sigma@localhost:5432/sigma"

    # §3.6 LLM layer — optional by design: without a key the deterministic
    # template path is used and the product still works.
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-5"
    anthropic_max_tokens: int = 1024

    # §3.1 upload limits
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB
    allowed_upload_extensions: tuple[str, ...] = (".csv", ".xlsx")

    # §5 KVKK: uploaded datasets are encrypted at rest.
    storage_dir: Path = BACKEND_ROOT / "storage"
    #: Fernet key. Generated per-process when unset so development works out of
    #: the box; MUST be set in any deployment or stored files become unreadable
    #: after a restart.
    storage_encryption_key: Optional[str] = None

    # §3.10 credits
    free_trial_credits: int = 1

    cors_origins: tuple[str, ...] = ("http://localhost:3000",)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
