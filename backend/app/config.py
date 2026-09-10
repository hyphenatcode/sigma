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

    # --- Auth (§7: Supabase) ------------------------------------------------
    #: Project URL, e.g. https://abcdefgh.supabase.co. Used to derive both the
    #: JWKS endpoint and the expected issuer, so it is the only value most
    #: deployments need to set.
    supabase_url: Optional[str] = None
    #: Legacy symmetric secret (HS256). Projects migrated to asymmetric signing
    #: keys do not need it; projects that have not, do.
    supabase_jwt_secret: Optional[str] = None
    #: Overrides the URL derived from `supabase_url` — for self-hosted Auth.
    supabase_jwks_url: Optional[str] = None
    #: Supabase sets `aud` to "authenticated" for signed-in users.
    supabase_audience: str = "authenticated"
    #: Tolerance for clock skew between this server and Supabase.
    jwt_leeway_seconds: int = 10

    #: Development escape hatch: identify the caller by an X-User-Email header.
    #: This is NOT authentication — anyone can claim any identity. Production
    #: refuses to start with it enabled (see validate_production_settings).
    allow_insecure_header_auth: bool = False

    # §3.10 credits
    free_trial_credits: int = 1

    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    @property
    def resolved_jwks_url(self) -> Optional[str]:
        """Where to fetch the project's public signing keys."""
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        return None

    @property
    def expected_issuer(self) -> Optional[str]:
        """The `iss` a token from this project must carry.

        Returns None when `supabase_url` is unset, which disables the issuer
        check — acceptable only when the symmetric secret is the sole
        verification path, since that secret is already project-specific. With
        JWKS there is no such binding, which is why production requires the URL.
        """
        if not self.supabase_url:
            return None
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def auth_configured(self) -> bool:
        return bool(self.supabase_jwt_secret or self.resolved_jwks_url)


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
    if config.allow_insecure_header_auth:
        problems.append(
            "ALLOW_INSECURE_HEADER_AUTH is enabled. That header is not "
            "authentication — any caller could claim any user's identity and "
            "read their uploaded data."
        )
    if not config.auth_configured:
        problems.append(
            "Supabase auth is not configured. Set SUPABASE_URL (and "
            "SUPABASE_JWT_SECRET if the project still uses legacy HS256 "
            "signing), or the API would have no way to authenticate anyone."
        )
    elif config.resolved_jwks_url and not config.supabase_url:
        problems.append(
            "SUPABASE_JWKS_URL is set without SUPABASE_URL, so the issuer "
            "claim cannot be checked and a token from any other Supabase "
            "project signed by the same key set would be accepted."
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
