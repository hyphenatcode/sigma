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
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_production_settings(config)

    message = str(excinfo.value)
    for expected in ["STORAGE_ENCRYPTION_KEY", "DATABASE_URL", "DEBUG", "CORS_ORIGINS"]:
        assert expected in message


@pytest.mark.parametrize("environment", ["development", "test", "staging", ""])
def test_non_production_environments_are_left_alone(environment):
    """Local development stays a two-command setup."""
    validate_production_settings(Settings(
        environment=environment,
        storage_encryption_key=None,
        debug=True,
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


def test_debug_defaults_to_off():
    """A deployment that forgets to set DEBUG gets the safe behaviour."""
    assert Settings(_env_file=None).debug is False
