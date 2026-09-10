"""Application settings, read from the environment (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    # Absolute paths, not a bare ".env": pydantic-settings resolves a relative
    # env_file against the *working directory*, so a repo-root .env was silently
    # ignored whenever the app was started from backend/ — which is exactly how
    # the README says to start it. Both locations are read, backend/.env last so
    # it can override for a per-checkout tweak.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Sigma"
    environment: str = "development"
    # Safe by default: a deployment that forgets to set DEBUG gets the
    # production behaviour, not the development one.
    debug: bool = False

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

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")


class ConfigurationError(RuntimeError):
    """A deployment is misconfigured in a way that must not start."""


#: The DATABASE_URL shipped in .env.example. Reaching production with this
#: still set means the real database was never configured.
_DEFAULT_DATABASE_URL = "postgresql+psycopg2://sigma:sigma@localhost:5432/sigma"


def validate_production_settings(config: "Settings | None" = None) -> None:
    """Refuse to start a production deployment that is misconfigured.

    Every check here guards a failure that is otherwise silent. The storage key
    is the worst of them: without it the app happily starts, encrypts uploads
    with a per-process key, and loses every dataset at the next restart — which
    is exactly what happened to this project's own container during
    development. Better to fail at boot with a message than to discover it from
    a user whose thesis data is gone.

    Non-production environments are left alone so local development stays a
    two-command setup.
    """
    config = config or get_settings()
    if not config.is_production:
        return

    problems: list[str] = []

    if not config.storage_encryption_key:
        problems.append(
            "STORAGE_ENCRYPTION_KEY is not set. Uploaded datasets would be "
            "encrypted with an ephemeral per-process key and become unreadable "
            "after the next restart."
        )
    if config.database_url == _DEFAULT_DATABASE_URL:
        problems.append(
            "DATABASE_URL is still the example value from .env.example."
        )
    if config.debug:
        problems.append("DEBUG must be false in production.")
    localhost_origins = [o for o in config.cors_origins
                         if "localhost" in o or "127.0.0.1" in o]
    if localhost_origins:
        problems.append(
            f"CORS_ORIGINS still contains development origins: "
            f"{', '.join(localhost_origins)}."
        )
    if not config.anthropic_api_key:
        # Not fatal by design: §3.6's deterministic templates make the LLM
        # optional, and the statistics are identical either way.
        pass

    if problems:
        raise ConfigurationError(
            "Refusing to start in production with an unsafe configuration:\n  - "
            + "\n  - ".join(problems)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
