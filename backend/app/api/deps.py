"""Shared API dependencies.

`get_current_user` is the only place identity is established. Everything else
scopes by `User.id` and knows nothing about how that user was authenticated.

Two paths reach it:

- **Supabase (§7)** — an `Authorization: Bearer <jwt>` header, verified
  cryptographically in `app.auth`. This is the real one.
- **The development header** — `X-User-Email`, allowed only when
  `ALLOW_INSECURE_HEADER_AUTH` is on. It is NOT authentication: any caller can
  claim any identity. It exists so local development and the test suite do not
  need a live Supabase project, and `validate_production_settings` refuses to
  start a production deployment with it enabled.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import AuthError, SupabaseClaims, get_verifier
from app.config import settings
from app.db import get_db
from app.models import CreditLedger, User

logger = logging.getLogger(__name__)

#: §3.10: university domains that qualify for the free tier. Turkish academic
#: addresses are all under .edu.tr.
UNIVERSITY_EMAIL_SUFFIXES = (".edu.tr", ".edu")

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Oturum doğrulanamadı. Lütfen tekrar giriş yapın.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _is_university_email(email: str) -> bool:
    return email.lower().endswith(UNIVERSITY_EMAIL_SUFFIXES)


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_current_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_email: Optional[str] = Header(default=None, alias="X-User-Email"),
    db: Session = Depends(get_db),
) -> User:
    token = _bearer_token(authorization)
    if token:
        verifier = get_verifier()
        if not verifier.configured:
            # Refusing is the safe failure: a misconfigured deployment must not
            # quietly fall through to the insecure header path.
            logger.error("Bearer token received but Supabase auth is not configured")
            raise _UNAUTHENTICATED
        try:
            claims = verifier.verify(token)
        except AuthError as exc:
            # `detail` is logged, never returned — which check failed is not
            # information an unauthenticated caller should get.
            logger.info("Token rejected: %s", exc.detail or exc.message_tr)
            raise _UNAUTHENTICATED from exc
        return _user_from_claims(db, claims)

    if settings.allow_insecure_header_auth and x_user_email:
        return _user_from_dev_header(db, x_user_email)

    raise _UNAUTHENTICATED


def _user_from_claims(db: Session, claims: SupabaseClaims) -> User:
    """Find or provision the local row for a verified Supabase user."""
    user = (
        db.query(User)
        .filter(User.auth_provider_id == claims.subject)
        .one_or_none()
    )

    email = (claims.email or "").strip().lower()

    if user is None and email:
        # A row may predate Supabase (or have been created by the dev header).
        # Claim it on first real sign-in rather than orphaning its datasets.
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is not None and user.auth_provider_id is None:
            user.auth_provider_id = claims.subject

    if user is None:
        user = _provision(db, email or f"{claims.subject}@unknown.invalid",
                          auth_provider_id=claims.subject,
                          email_confirmed=claims.email_verified)
        return user

    if email and user.email != email:
        user.email = email

    # §3.10: the free tier needs a *confirmed* university address. Supabase
    # owns confirmation; we only add the domain rule.
    user.university_email_verified = bool(
        claims.email_verified and email and _is_university_email(email)
    )
    db.commit()
    db.refresh(user)
    return user


def _user_from_dev_header(db: Session, raw_email: str) -> User:
    email = raw_email.strip().lower()
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = _provision(db, email, auth_provider_id=None,
                          email_confirmed=True)  # nothing to confirm against
    return user


def _provision(db: Session, email: str, *, auth_provider_id: Optional[str],
               email_confirmed: bool) -> User:
    user = User(
        email=email,
        auth_provider_id=auth_provider_id,
        university_email_verified=bool(email_confirmed and _is_university_email(email)),
    )
    db.add(user)
    db.flush()
    # §3.10: the free trial is one analysis.
    db.add(CreditLedger(
        user_id=user.id,
        package_type="free_trial",
        credits_remaining=settings.free_trial_credits,
    ))
    db.commit()
    db.refresh(user)
    return user


def remaining_credits(db: Session, user: User) -> int:
    entries = db.query(CreditLedger).filter(CreditLedger.user_id == user.id).all()
    return sum(entry.credits_remaining for entry in entries)


def consume_credit(db: Session, user: User) -> None:
    """Spend one credit, oldest package first. Raises 402 when there are none."""
    entries = (
        db.query(CreditLedger)
        .filter(CreditLedger.user_id == user.id, CreditLedger.credits_remaining > 0)
        .order_by(CreditLedger.purchased_at.asc())
        .all()
    )
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Analiz krediniz kalmadı. Devam etmek için kredi paketi "
                "satın alabilirsiniz."
            ),
        )
    entries[0].credits_remaining -= 1
    db.flush()
