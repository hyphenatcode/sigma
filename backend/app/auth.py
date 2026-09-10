"""Supabase Auth token verification (§7).

Replaces the development `X-User-Email` seam with real cryptographic identity.
Supabase issues session JWTs signed either with the project's legacy symmetric
secret (HS256) or, on projects using asymmetric signing keys, with an ES256/RS256
key whose public half is published at the project's JWKS endpoint. Both are
supported, because which one a project uses is not something this code can
choose.

Security notes, in order of how badly they bite:

1. **Algorithm confusion.** The single most common JWT verification bug is
   letting the token choose which key verifies it. If a server accepts both
   HS256 and RS256/ES256 and picks the key from the token's own `alg`, an
   attacker takes the *public* key (which is public!) and uses it as an HMAC
   secret to forge an HS256 token. `_key_for` therefore returns the key and the
   permitted algorithm list *together*, and the symmetric secret is only ever
   reachable from the HS256 branch. There is a test that forges exactly this
   attack and asserts it is rejected.
2. **Signature, expiry, audience and issuer are all verified.** Skipping `aud`
   or `iss` would let a token minted by a *different* Supabase project
   authenticate against this one.
3. **Unknown `kid` triggers at most one JWKS refetch per cooldown**, so a
   stream of tokens bearing junk key ids cannot be used to hammer the JWKS
   endpoint through us.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import jwt
from jwt import PyJWKSet

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

#: Supabase signs with HS256 (legacy shared secret) or ES256/RS256 (asymmetric
#: signing keys). Anything else — notably "none" — is refused outright.
SYMMETRIC_ALGORITHMS = frozenset({"HS256"})
ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256"})

#: How long a fetched JWKS is trusted before a routine refresh.
JWKS_CACHE_SECONDS = 600
#: Minimum gap between refetches forced by an unknown `kid`.
JWKS_REFRESH_COOLDOWN_SECONDS = 30


class AuthError(Exception):
    """Token could not be verified. Surfaces to the caller as HTTP 401.

    The message is deliberately coarse: telling an attacker whether the
    signature, the audience or the expiry failed is free information.
    """

    def __init__(self, message_tr: str = "Oturum doğrulanamadı.", *, detail: str = ""):
        super().__init__(detail or message_tr)
        self.message_tr = message_tr
        self.detail = detail


@dataclass(frozen=True)
class SupabaseClaims:
    """The parts of a verified Supabase token this application uses."""

    subject: str          # `sub` — the stable Supabase user UUID
    email: Optional[str]
    email_verified: bool
    role: Optional[str]
    raw: dict[str, Any] = field(default_factory=dict)


class _JWKSCache:
    """Caches a project's public signing keys.

    Supabase rotates asymmetric keys, so an unknown `kid` is a normal event and
    must trigger a refetch — but only at a bounded rate, or a forged token with
    a random `kid` becomes an amplification vector.
    """

    def __init__(self, url: str, *, timeout: float = 5.0):
        self._url = url
        self._timeout = timeout
        self._lock = threading.Lock()
        self._keys: Optional[PyJWKSet] = None
        self._fetched_at = 0.0
        self._last_forced_refresh = 0.0

    def _fetch(self) -> PyJWKSet:
        try:
            response = httpx.get(self._url, timeout=self._timeout)
            response.raise_for_status()
            key_set = PyJWKSet.from_dict(response.json())
        except Exception as exc:  # noqa: BLE001 — surfaced as a 401, never a 500
            raise AuthError(detail=f"JWKS could not be fetched from {self._url}: {exc}") from exc
        self._keys = key_set
        self._fetched_at = time.monotonic()
        return key_set

    def key_for(self, kid: Optional[str]):
        now = time.monotonic()
        with self._lock:
            stale = self._keys is None or (now - self._fetched_at) > JWKS_CACHE_SECONDS
            if stale:
                self._fetch()

            key = self._lookup(kid)
            if key is not None:
                return key

            # Unknown kid: the project may have rotated. Refetch, rate-limited.
            if (now - self._last_forced_refresh) > JWKS_REFRESH_COOLDOWN_SECONDS:
                self._last_forced_refresh = now
                self._fetch()
                key = self._lookup(kid)
                if key is not None:
                    return key

        raise AuthError(detail=f"No signing key matches kid={kid!r}")

    def _lookup(self, kid: Optional[str]):
        if self._keys is None:
            return None
        for key in self._keys.keys:
            # A JWKS may carry keys reserved for encryption; only signing keys
            # are candidates here.
            if getattr(key, "public_key_use", "sig") not in (None, "sig"):
                continue
            if kid is None or key.key_id == kid:
                return key
        return None


class SupabaseTokenVerifier:
    """Verifies Supabase session JWTs against a project's configuration."""

    def __init__(self, config: Optional[Settings] = None):
        self._config = config or get_settings()
        self._jwks: Optional[_JWKSCache] = None
        jwks_url = self._config.resolved_jwks_url
        if jwks_url:
            self._jwks = _JWKSCache(jwks_url)

    @property
    def configured(self) -> bool:
        return bool(self._config.supabase_jwt_secret or self._jwks)

    def _key_for(self, header: dict[str, Any]) -> tuple[Any, list[str]]:
        """Pick the verification key AND the algorithms allowed with it.

        Returning them together is what prevents algorithm confusion: the
        symmetric secret is unreachable from the asymmetric branch and vice
        versa, so a token cannot nominate a key of the wrong family.
        """
        algorithm = header.get("alg")

        if algorithm in SYMMETRIC_ALGORITHMS:
            secret = self._config.supabase_jwt_secret
            if not secret:
                raise AuthError(detail="HS256 token received but SUPABASE_JWT_SECRET is unset")
            return secret, sorted(SYMMETRIC_ALGORITHMS)

        if algorithm in ASYMMETRIC_ALGORITHMS:
            if self._jwks is None:
                raise AuthError(detail=f"{algorithm} token received but no JWKS URL is configured")
            key = self._jwks.key_for(header.get("kid"))
            # Restrict to the algorithm this key was actually published for,
            # falling back to the header's only when the JWK does not say.
            key_algorithm = getattr(key, "algorithm_name", None) or algorithm
            if key_algorithm not in ASYMMETRIC_ALGORITHMS:
                raise AuthError(detail=f"Unsupported key algorithm {key_algorithm!r}")
            return key.key, [key_algorithm]

        raise AuthError(detail=f"Unsupported token algorithm {algorithm!r}")

    def verify(self, token: str) -> SupabaseClaims:
        if not token or token.count(".") != 2:
            raise AuthError(detail="Malformed token")

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError(detail=f"Unreadable token header: {exc}") from exc

        key, algorithms = self._key_for(header)

        issuer = self._config.expected_issuer
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=self._config.supabase_audience,
                issuer=issuer,  # None disables the check; see config for when
                options={
                    "require": ["exp", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": bool(issuer),
                },
                leeway=self._config.jwt_leeway_seconds,
            )
        except jwt.PyJWTError as exc:
            raise AuthError(detail=f"{type(exc).__name__}: {exc}") from exc

        subject = payload.get("sub")
        if not subject:
            raise AuthError(detail="Token carries no subject")

        return SupabaseClaims(
            subject=str(subject),
            email=(payload.get("email") or None),
            email_verified=_email_verified(payload),
            role=payload.get("role"),
            raw=payload,
        )


def _email_verified(payload: dict[str, Any]) -> bool:
    """Whether Supabase considers the address confirmed.

    Supabase puts this in `user_metadata` on most projects and sometimes at the
    top level. Absent means unconfirmed: §3.10 uses this for the free tier, so
    the safe default is the one that grants nothing.

    Note this only means anything if the project has "Confirm email" enabled —
    a project that does not require confirmation will mint tokens for
    unconfirmed addresses.
    """
    metadata = payload.get("user_metadata") or {}
    for source in (payload, metadata):
        value = source.get("email_verified")
        if isinstance(value, bool):
            return value
    return False


_verifier: Optional[SupabaseTokenVerifier] = None
_verifier_lock = threading.Lock()


def get_verifier() -> SupabaseTokenVerifier:
    """Process-wide verifier, so the JWKS cache is shared across requests."""
    global _verifier
    if _verifier is None:
        with _verifier_lock:
            if _verifier is None:
                _verifier = SupabaseTokenVerifier()
    return _verifier


def reset_verifier() -> None:
    """Drop the cached verifier. Used by tests that change configuration."""
    global _verifier
    with _verifier_lock:
        _verifier = None
