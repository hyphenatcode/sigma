"""Credit endpoints (§6, §3.10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, remaining_credits
from app.db import get_db
from app.models import CreditLedger, User
from app.schemas import CreditsOut, PurchaseIn, PurchaseOut

router = APIRouter(prefix="/api/credits", tags=["credits"])

#: §3.10 package catalogue. Prices are a product decision, not an engineering
#: one, so only the credit grants live here.
PACKAGES: dict[str, int] = {
    "free_trial": 1,
    "single_analysis": 1,
    "thesis_bundle": 10,
}


@router.get("", response_model=CreditsOut)
def get_credits(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CreditsOut:
    entries = db.query(CreditLedger).filter(CreditLedger.user_id == user.id).all()
    return CreditsOut(
        credits_remaining=remaining_credits(db, user),
        entries=[
            {
                "id": entry.id,
                "package_type": entry.package_type,
                "credits_remaining": entry.credits_remaining,
                "purchased_at": entry.purchased_at.isoformat(),
                "payment_reference": entry.payment_reference,
            }
            for entry in entries
        ],
    )


@router.post("/purchase", response_model=PurchaseOut,
             status_code=status.HTTP_202_ACCEPTED)
def purchase_credits(
    payload: PurchaseIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PurchaseOut:
    """§6: initiate the payment flow (İyzico redirect).

    The İyzico integration is NOT implemented. It needs merchant credentials, a
    KDV-compliant invoice flow and a callback endpoint that verifies the
    payment signature — none of which can be built or tested without a real
    merchant account, and faking it would create a route that appears to take
    money and does not.

    This endpoint therefore validates the package and returns `pending` without
    granting credits. `_grant_credits` below is the function the İyzico
    callback will call once the payment is verified.
    """
    if payload.package_type not in PACKAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz paket türü: {payload.package_type}",
        )

    # TODO(integration): create an İyzico checkout form, persist the
    # conversation id against the user, and grant credits from the verified
    # callback via _grant_credits(). Requires merchant credentials.
    return PurchaseOut(
        status="pending",
        package_type=payload.package_type,
        redirect_url=None,
        message_tr=(
            "Ödeme altyapısı (İyzico) entegrasyonu bu sürümde henüz aktif "
            "değildir. Kredi tanımlanmamıştır."
        ),
    )


def _grant_credits(
    db: Session, user: User, package_type: str, payment_reference: str
) -> CreditLedger:
    """Called once a payment is verified. Not reachable until İyzico is wired."""
    entry = CreditLedger(
        user_id=user.id,
        package_type=package_type,
        credits_remaining=PACKAGES[package_type],
        payment_reference=payment_reference,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
