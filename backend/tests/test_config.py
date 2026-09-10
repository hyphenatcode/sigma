"""Production configuration guardrails.

Each check here guards a failure that is otherwise silent — the app starts,
looks healthy, and is wrong. The storage key is the one that actually bit this
project during development: without it the app encrypts uploads with a
per-process key and loses every dataset at the next restart.
"""

import pytest

from app.config import (
    ConfigurationError,
    Settings,
    validate_production_settings,
)

PRODUCTION_SAFE = dict(
    environment="production",
    storage_encryption_key="A" * 43 + "=",
    database_url="postgresql+psycopg2://sigma:secret@db.internal:5432/sigma",
    debug=False,
    cors_origins=("https://sigma.app",),
    supabase_url="https://abcdefgh.supabase.co",
    allow_insecure_header_auth=False,
    r2_account_id="abc123",
    r2_access_key_id="key",
    r2_secret_access_key="secret",
    r2_bucket="sigma",
)


def test_a_correctly_configured_production_deployment_starts():
    validate_production_settings(Settings(**PRODUCTION_SAFE))


@pytest.mark.parametrize("override,expected", [
    ({"storage_encryption_key": None}, "STORAGE_ENCRYPTION_KEY"),
    ({"database_url": "postgresql+psycopg2://sigma:sigma@localhost:5432/sigma"},
     "DATABASE_URL"),
    ({"debug": True}, "DEBUG"),
    ({"cors_origins": ("http://localhost:3000",)}, "CORS_ORIGINS"),
    ({"cors_origins": ("https://sigma.app", "http://127.0.0.1:3000")}, "CORS_ORIGINS"),
    # Auth guardrails: the header seam is not authentication, and a deployment
    # with no Supabase configuration cannot authenticate anyone at all.
    ({"allow_insecure_header_auth": True}, "ALLOW_INSECURE_HEADER_AUTH"),
    ({"supabase_url": None, "supabase_jwt_secret": None}, "Supabase auth is not configured"),
    # JWKS without the project URL means the issuer cannot be checked, so a
    # token from any project sharing that key set would be accepted.
    ({"supabase_url": None,
      "supabase_jwks_url": "https://x.supabase.co/auth/v1/.well-known/jwks.json"},
     "issuer"),
    # A container filesystem does not survive a redeploy, so production
    # without object storage would silently lose every upload.
    ({"r2_bucket": None}, "Object storage is not configured"),
    ({"r2_access_key_id": None}, "Object storage is not configured"),
    ({"r2_account_id": None, "r2_endpoint_url": None}, "Object storage is not configured"),
])
def test_unsafe_production_configuration_refuses_to_start(override, expected):
    config = Settings(**{**PRODUCTION_SAFE, **override})
    with pytest.raises(ConfigurationError) as excinfo:
        validate_production_settings(config)
    assert expected in str(excinfo.value)


def test_all_problems_are_reported_at_once():
    """A deployment with three mistakes should learn about three mistakes, not
    discover them one restart at a time."""
    config = Settings(
        environment="production",
        storage_encryption_key=None,
        database_url="postgresql+psycopg2://sigma:sigma@localhost:5432/sigma",
        debug=True,
        cors_origins=("http://localhost:3000",),
        supabase_url=None,
        supabase_jwt_secret=None,
        allow_insecure_header_auth=True,
        r2_bucket=None,
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_production_settings(config)

    message = str(excinfo.value)
    for expected in ["STORAGE_ENCRYPTION_KEY", "DATABASE_URL", "DEBUG",
                     "CORS_ORIGINS", "ALLOW_INSECURE_HEADER_AUTH", "Supabase",
                     "Object storage"]:
        assert expected in message


@pytest.mark.parametrize("environment", ["development", "test", "staging", ""])
def test_non_production_environments_are_left_alone(environment):
    """Local development stays a two-command setup."""
    validate_production_settings(Settings(
        environment=environment,
        storage_encryption_key=None,
        debug=True,
        allow_insecure_header_auth=True,
    ))


@pytest.mark.parametrize("environment,expected", [
    ("production", True), ("PRODUCTION", True), ("prod", True),
    (" production ", True), ("development", False), ("staging", False),
])
def test_is_production_detection(environment, expected):
    assert Settings(environment=environment).is_production is expected


def test_missing_llm_key_is_not_a_production_blocker():
    """§3.6's deterministic templates make the LLM optional — the statistics
    are identical either way, so a missing key must not stop a deployment."""
    validate_production_settings(Settings(**{**PRODUCTION_SAFE, "anthropic_api_key": None}))


def test_a_symmetric_only_project_is_accepted():
    """A project still on legacy HS256 signing has no JWKS, and that is fine
    as long as the secret is set — the secret is already project-specific."""
    validate_production_settings(Settings(**{
        **PRODUCTION_SAFE,
        "supabase_jwt_secret": "the-projects-legacy-jwt-secret-value",
    }))


def test_insecure_header_auth_defaults_to_off():
    """The dev seam must be opt-in, so forgetting to disable it is impossible."""
    assert Settings(_env_file=None).allow_insecure_header_auth is False


def test_debug_defaults_to_off():
    """A deployment that forgets to set DEBUG gets the safe behaviour."""
    assert Settings(_env_file=None).debug is False


# ---------------------------------------------------------------------------
# Connection strings as hosting dashboards actually present them
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("given,expected_driver", [
    # Supabase and Railway both show this form; SQLAlchemy resolves it itself.
    ("postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres", "psycopg2"),
    ("postgresql://u:pw@aws-0-eu-central-1.pooler.supabase.com:5432/postgres", "psycopg2"),
    # Some platforms still emit the older scheme, which SQLAlchemy rejects with
    # "Can't load plugin: sqlalchemy.dialects:postgres" — an error that says
    # nothing useful, on first boot after a deploy.
    ("postgres://u:pw@host:5432/db", "psycopg2"),
    ("postgresql+psycopg2://sigma:sigma@localhost:5432/sigma", "psycopg2"),
])
def test_platform_connection_strings_are_usable(given, expected_driver):
    from sqlalchemy import create_engine

    url = Settings(database_url=given, _env_file=None).database_url
    assert create_engine(url).dialect.driver == expected_driver


def test_legacy_postgres_scheme_is_rewritten_without_touching_credentials():
    config = Settings(
        database_url="postgres://user:p%40ss@host.example:5432/db?sslmode=require",
        _env_file=None,
    )
    assert config.database_url == (
        "postgresql+psycopg2://user:p%40ss@host.example:5432/db?sslmode=require"
    )
