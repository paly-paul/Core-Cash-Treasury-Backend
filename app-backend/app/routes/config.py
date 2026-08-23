from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.auth.models import UserModel
from app.database import get_db
from app.models.fx_rates import FXRate

router = APIRouter()


@router.get("/api/config/fx-rates")
async def get_fx_rates(
    date_param: Optional[str] = Query(None, alias="date"),
    currency_from: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict:
    """GET /api/config/fx-rates - Get FX rates for client."""
    from datetime import datetime

    if date_param:
        rate_date = datetime.strptime(date_param, "%Y-%m-%d").date()
    else:
        rate_date = date.today()

    stmt = select(FXRate).where(
        (FXRate.client_id == current_user.client_id) & (FXRate.rate_date == rate_date)
    )

    if currency_from:
        stmt = stmt.where(FXRate.currency_from == currency_from)

    result = await db.execute(stmt)
    rates = result.scalars().all()

    rates_data = [
        {
            "id": str(r.id),
            "currency_from": r.currency_from,
            "currency_to": r.currency_to,
            "rate": float(r.rate),
            "rate_date": str(r.rate_date),
            "entered_by_email": r.entered_by,  # Would need join to get email
            "entered_at": r.entered_at.isoformat(),
        }
        for r in rates
    ]

    return {"rates": rates_data}


@router.post("/api/config/fx-rates", status_code=201)
async def create_or_update_fx_rate(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(
        require_role(["Analyst", "TreasuryManager", "CFO"])
    ),
) -> dict:
    """POST /api/config/fx-rates - Create or update FX rate."""
    from datetime import datetime

    currency_from = body["currency_from"]
    rate = Decimal(str(body["rate"]))
    rate_date = datetime.strptime(body.get("rate_date", str(date.today())), "%Y-%m-%d").date()

    # Try to find existing record
    stmt = select(FXRate).where(
        (FXRate.client_id == current_user.client_id)
        & (FXRate.currency_from == currency_from)
        & (FXRate.rate_date == rate_date)
    )
    result = await db.execute(stmt)
    existing = result.scalar()

    if existing:
        # Update
        existing.rate = rate
        existing.entered_by = current_user.id
        existing.entered_at = datetime.utcnow()
    else:
        # Create
        fx_rate = FXRate(
            client_id=current_user.client_id,
            currency_from=currency_from,
            currency_to="USD",
            rate=rate,
            rate_date=rate_date,
            entered_by=current_user.id,
        )
        db.add(fx_rate)
        existing = fx_rate

    await db.commit()
    await db.refresh(existing)

    return {
        "id": str(existing.id),
        "currency_from": existing.currency_from,
        "currency_to": existing.currency_to,
        "rate": float(existing.rate),
        "rate_date": str(existing.rate_date),
        "entered_at": existing.entered_at.isoformat(),
    }
