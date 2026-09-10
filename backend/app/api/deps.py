"""Shared API dependencies.

Authentication is a deliberate placeholder. §7 specifies Supabase Auth or Clerk
for v1, which is an integration rather than something to hand-roll, and §3.10's
university-email verification is a product decision still open in §10. Until
that lands, the API identifies the caller by an `X-User-Email` header and
creates the user row on first sight.

This is NOT security. It is a seam: `get_current_user` is the single place a
real token verifier plugs into, and no other module knows how identity is
established.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import CreditLedger, User

#: §3.10: university domains that qualify for the free tier. Turkish academic
#: addresses are all under .edu.tr.
UNIVERSITY_EMAIL_SUFFIXES = (".edu.tr", ".edu")


def _is_university_email(email: str) -> bool:
    return email.lower().endswith(UNIVERSITY_EMAIL_SUFFIXES)


def get_current_user(
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
    db: Session = Depends(get_db),
) -> User:
    if not x_user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kimlik doğrulanamadı. X-User-Email başlığı gereklidir.",
        )

    email = x_user_email.strip().lower()
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(
            email=email,
            university_email_verified=_is_university_email(email),
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
