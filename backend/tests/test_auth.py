"""Supabase token verification (§7).

Tokens here are minted with keys generated in the test itself, so these
exercise the real verification path rather than a mock of it. The one that
matters most is `test_algorithm_confusion_attack_is_rejected`: it forges the
classic JWT attack and asserts it fails.
"""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.auth import AuthError, SupabaseTokenVerifier, reset_verifier
from app.config import Settings

PROJECT_URL = "https://abcdefgh.supabase.co"
ISSUER = f"{PROJECT_URL}/auth/v1"
JWKS_URL = f"{PROJECT_URL}/auth/v1/.well-known/jwks.json"
SECRET = "a-legacy-supabase-jwt-secret-value-long-enough"
KID = "test-signing-key-1"


@pytest.fixture(autouse=True)
def _reset():
    reset_verifier()
    yield
    reset_verifier()


@pytest.fixture
def ec_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def jwks(ec_key):
    key = json.loads(ECAlgorithm.to_jwk(ec_key.public_key()))
    key.update({"kid": KID, "use": "sig", "alg": "ES256"})
    return {"keys": [key]}


def claims(**overrides: Any) -> dict[str, Any]:
    payload = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "aud": "authenticated",
        "iss": ISSUER,
        "role": "authenticated",
        "email": "arastirmaci@universite.edu.tr",
        "user_metadata": {"email_verified": True},
        "iat": int(time.time()) - 10,
        "exp": int(time.time()) + 3600,
    }
    payload.update(overrides)
    return payload


def hs256(**overrides: Any) -> str:
    return jwt.encode(claims(**overrides), SECRET, algorithm="HS256")


def es256(ec_key, **overrides: Any) -> str:
    return jwt.encode(claims(**overrides), ec_key,
                      algorithm="ES256", headers={"kid": KID})


def symmetric_verifier() -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(Settings(
        supabase_url=PROJECT_URL, supabase_jwt_secret=SECRET, _env_file=None))


def asymmetric_verifier(monkeypatch, jwks) -> SupabaseTokenVerifier:
    """A verifier with JWKS only — no symmetric secret configured."""
    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return jwks

    monkeypatch.setattr("app.auth.httpx.get", lambda *a, **k: _Response())
    return SupabaseTokenVerifier(Settings(
        supabase_url=PROJECT_URL, supabase_jwt_secret=None, _env_file=None))


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_valid_hs256_token_is_accepted():
    result = symmetric_verifier().verify(hs256())
    assert result.subject == "11111111-2222-3333-4444-555555555555"
    assert result.email == "arastirmaci@universite.edu.tr"
    assert result.email_verified is True
    assert result.role == "authenticated"


def test_valid_es256_token_is_accepted(monkeypatch, jwks, ec_key):
    result = asymmetric_verifier(monkeypatch, jwks).verify(es256(ec_key))
    assert result.subject == "11111111-2222-3333-4444-555555555555"
    assert result.email_verified is True


def test_email_verified_defaults_to_false_when_absent():
    """§3.10 gates the free tier on this, so absent must mean "not verified"."""
    token = hs256(user_metadata={})
    assert symmetric_verifier().verify(token).email_verified is False


def test_email_verified_read_from_top_level_claim():
    token = hs256(user_metadata={}, email_verified=True)
    assert symmetric_verifier().verify(token).email_verified is True


# ---------------------------------------------------------------------------
# The attack this design exists to stop
# ---------------------------------------------------------------------------

def _forge_hs256(payload: dict[str, Any], secret: bytes, kid: str) -> str:
    """Hand-assemble an HS256 token.

    PyJWT refuses to sign with an asymmetric PEM as the HMAC key, which is a
    good guard — but an attacker is not using PyJWT. Building the token from
    base64 segments and a raw HMAC is what the attack actually looks like.
    """
    import base64
    import hashlib
    import hmac

    def segment(data: dict[str, Any]) -> bytes:
        raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    signing_input = b".".join([
        segment({"alg": "HS256", "typ": "JWT", "kid": kid}),
        segment(payload),
    ])
    signature = base64.urlsafe_b64encode(
        hmac.new(secret, signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    return (signing_input + b"." + signature).decode()


def test_algorithm_confusion_attack_is_rejected(monkeypatch, jwks, ec_key):
    """The classic JWT forgery: take the PUBLIC key — which is published at the
    JWKS endpoint for anyone to read — and use it as an HMAC secret to mint an
    HS256 token.

    A server that picks its verification key from the token's own `alg` header
    accepts this and hands the attacker any account they name. Ours must not:
    `_key_for` returns the key and the permitted algorithms together, so the
    HS256 branch can only ever reach the symmetric secret — which this
    verifier does not have.
    """
    from cryptography.hazmat.primitives import serialization

    public_pem = ec_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    forged = _forge_hs256(claims(sub="attacker-controlled"), public_pem, KID)

    # Sanity check that the forgery is real: recompute the HMAC by hand and
    # confirm it matches. (PyJWT refuses to *decode* with an asymmetric PEM as
    # an HMAC key, which is its own defence in depth — so the check cannot go
    # through PyJWT, and an attacker would not either.)
    import base64
    import hashlib
    import hmac

    signing_input, _, signature = forged.rpartition(".")
    expected = base64.urlsafe_b64encode(
        hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    assert signature == expected, "the forged token is not actually signed"

    verifier = asymmetric_verifier(monkeypatch, jwks)
    with pytest.raises(AuthError) as excinfo:
        verifier.verify(forged)
    assert "SUPABASE_JWT_SECRET is unset" in excinfo.value.detail


def test_algorithm_confusion_rejected_even_when_a_secret_is_configured(
    monkeypatch, jwks, ec_key
):
    """The stronger case: a project running both signing schemes at once.

    Even with a symmetric secret available, the forged token must fail — the
    secret is the only key the HS256 branch will try, and it is not the public
    key the attacker signed with.
    """
    from cryptography.hazmat.primitives import serialization

    public_pem = ec_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    forged = _forge_hs256(claims(sub="attacker-controlled"), public_pem, KID)

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return jwks

    monkeypatch.setattr("app.auth.httpx.get", lambda *a, **k: _Response())
    verifier = SupabaseTokenVerifier(Settings(
        supabase_url=PROJECT_URL, supabase_jwt_secret=SECRET, _env_file=None))

    with pytest.raises(AuthError):
        verifier.verify(forged)


def test_alg_none_is_rejected():
    """An unsigned token must never authenticate anyone."""
    unsigned = jwt.encode(claims(), key="", algorithm="none")
    with pytest.raises(AuthError):
        symmetric_verifier().verify(unsigned)


# ---------------------------------------------------------------------------
# Standard claim checks
# ---------------------------------------------------------------------------

def test_expired_token_is_rejected():
    token = hs256(exp=int(time.time()) - 120, iat=int(time.time()) - 3600)
    with pytest.raises(AuthError):
        symmetric_verifier().verify(token)


def test_token_from_another_supabase_project_is_rejected():
    """Without the issuer check, any Supabase project's token would work."""
    token = hs256(iss="https://someoneelse.supabase.co/auth/v1")
    with pytest.raises(AuthError):
        symmetric_verifier().verify(token)


def test_wrong_audience_is_rejected():
    """`aud` separates a signed-in user's token from other Supabase tokens."""
    token = hs256(aud="anon")
    with pytest.raises(AuthError):
        symmetric_verifier().verify(token)


def test_tampered_signature_is_rejected():
    token = hs256()
    head, payload, signature = token.split(".")
    tampered = f"{head}.{payload}.{signature[:-4]}AAAA"
    with pytest.raises(AuthError):
        symmetric_verifier().verify(tampered)


def test_token_signed_with_the_wrong_secret_is_rejected():
    token = jwt.encode(claims(), "not-the-project-secret-but-long-enough-for-sha256",
                       algorithm="HS256")
    with pytest.raises(AuthError):
        symmetric_verifier().verify(token)


def test_token_without_a_subject_is_rejected():
    payload = claims()
    del payload["sub"]
    token = jwt.encode(payload, SECRET, algorithm="HS256")
    with pytest.raises(AuthError):
        symmetric_verifier().verify(token)


def test_token_without_an_expiry_is_rejected():
    payload = claims()
    del payload["exp"]
    token = jwt.encode(payload, SECRET, algorithm="HS256")
    with pytest.raises(AuthError):
        symmetric_verifier().verify(token)


@pytest.mark.parametrize("garbage", ["", "not-a-token", "a.b", "a.b.c.d", "...."])
def test_malformed_tokens_are_rejected(garbage):
    with pytest.raises(AuthError):
        symmetric_verifier().verify(garbage)


def test_unknown_kid_is_rejected(monkeypatch, jwks, ec_key):
    other_key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(claims(), other_key, algorithm="ES256",
                       headers={"kid": "a-kid-that-does-not-exist"})
    with pytest.raises(AuthError):
        asymmetric_verifier(monkeypatch, jwks).verify(token)


def test_asymmetric_token_without_jwks_configured_is_rejected(ec_key):
    verifier = SupabaseTokenVerifier(Settings(
        supabase_jwt_secret=SECRET, supabase_url=None, _env_file=None))
    with pytest.raises(AuthError) as excinfo:
        verifier.verify(es256(ec_key))
    assert "no JWKS URL" in excinfo.value.detail


def test_clock_skew_leeway_is_applied():
    """A token that expired a moment ago survives the configured leeway."""
    verifier = SupabaseTokenVerifier(Settings(
        supabase_url=PROJECT_URL, supabase_jwt_secret=SECRET,
        jwt_leeway_seconds=60, _env_file=None))
    token = hs256(exp=int(time.time()) - 5)
    assert verifier.verify(token).subject


# ---------------------------------------------------------------------------
# Failures must not describe themselves
# ---------------------------------------------------------------------------

def test_user_facing_message_does_not_reveal_which_check_failed():
    verifier = symmetric_verifier()
    messages = set()
    for token in [hs256(exp=1), hs256(aud="anon"),
                  jwt.encode(claims(), "wrong-secret-that-is-long-enough-for-sha256",
                              algorithm="HS256")]:
        try:
            verifier.verify(token)
        except AuthError as exc:
            messages.add(exc.message_tr)
    assert messages == {"Oturum doğrulanamadı."}


def test_verifier_reports_whether_it_is_configured():
    assert symmetric_verifier().configured is True
    assert SupabaseTokenVerifier(
        Settings(supabase_url=None, supabase_jwt_secret=None, _env_file=None)
    ).configured is False
