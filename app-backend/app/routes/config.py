from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from core_cash_shared.schemas.auth import UserClaims
from core_cash_shared.enums import Permission
from app.database import get_db
from app.models.fx_rates import FXRate
from app.models.system_config import SystemConfig
from app.models.investment import InvestmentPolicy, InvestmentCutoff
from app.models.legal_entity import LegalEntity
from app.models.account import Account
from app.services.audit_service import write_audit_event

router = APIRouter()

VALID_CURRENCIES = {"GBP", "EUR"}


@router.get("/api/config/fx-rates")
async def get_fx_rates(
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """GET /api/config/fx-rates - Get FX rates for client."""
    today = date.today()

    stmt = select(FXRate).where(
        (FXRate.client_id == current_user.client_id) & (FXRate.rate_date == today)
    )
    result = await db.execute(stmt)
    today_rates = result.scalars().all()

    today_entered = len(today_rates) > 0

    seven_days_ago = today - timedelta(days=7)
    stmt = select(FXRate).where(
        and_(
            FXRate.client_id == current_user.client_id,
            FXRate.rate_date >= seven_days_ago,
        )
    ).order_by(desc(FXRate.rate_date))

    result = await db.execute(stmt)
    prior_rates_all = result.scalars().all()

    rates_data = [
        {
            "id": str(r.id),
            "currency_from": r.currency_from,
            "currency_to": r.currency_to,
            "rate": float(r.rate),
            "rate_date": str(r.rate_date),
        }
        for r in today_rates
    ]

    prior_rates_data = [
        {
            "id": str(r.id),
            "currency_from": r.currency_from,
            "currency_to": r.currency_to,
            "rate": float(r.rate),
            "rate_date": str(r.rate_date),
        }
        for r in prior_rates_all
    ]

    return {
        "today_entered": today_entered,
        "warning": not today_entered,
        "rates": rates_data,
        "prior_rates": prior_rates_data,
    }


@router.post("/api/config/fx-rates", status_code=201)
async def create_or_update_fx_rate(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_ASSUMPTIONS)),
) -> dict:
    """POST /api/config/fx-rates - Create or update FX rates."""
    from uuid import UUID as UUIDType

    rates_to_enter = body.get("rates", [])
    rate_date = date.today()
    rates_entered = 0
    warning_cleared = False

    user_id_uuid = UUIDType(current_user.user_id)

    for rate_item in rates_to_enter:
        currency_from = rate_item.get("currency_from", "").upper()
        rate = Decimal(str(rate_item.get("rate", 1)))

        if currency_from not in VALID_CURRENCIES:
            raise HTTPException(status_code=422, detail=f"Invalid currency: {currency_from}")

        stmt = select(FXRate).where(
            and_(
                FXRate.client_id == current_user.client_id,
                FXRate.currency_from == currency_from,
                FXRate.rate_date == rate_date,
            )
        )
        result = await db.execute(stmt)
        existing = result.scalar()

        if existing:
            existing.rate = rate
            existing.entered_by = user_id_uuid
            existing.entered_at = datetime.utcnow()
        else:
            fx_rate = FXRate(
                client_id=current_user.client_id,
                currency_from=currency_from,
                currency_to="USD",
                rate=rate,
                rate_date=rate_date,
                entered_by=user_id_uuid,
            )
            db.add(fx_rate)

        rates_entered += 1

        await write_audit_event(
            db=db,
            client_id=current_user.client_id,
            user_id=user_id_uuid,
            user_name=current_user.email,
            action="config.fx_rate_entered",
            entity_type="fx_rate",
            new_value={
                "currency_from": currency_from,
                "rate": float(rate),
                "rate_date": str(rate_date),
            },
            ip_address=request.client.host if request.client else "0.0.0.0",
        )

    await db.commit()

    stmt = select(FXRate).where(
        (FXRate.client_id == current_user.client_id) & (FXRate.rate_date == rate_date)
    )
    result = await db.execute(stmt)
    today_rates = result.scalars().all()

    return {
        "rate_date": str(rate_date),
        "rates_entered": rates_entered,
        "warning_cleared": len(today_rates) > 0,
    }


@router.get("/api/config/investment-policy")
async def get_investment_policy(
    entity_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """GET /api/config/investment-policy - Get active investment policy."""
    from uuid import UUID as UUIDType

    if entity_id:
        try:
            entity_uuid = UUIDType(entity_id)
        except ValueError:
            return {"policy": None}

        stmt = select(InvestmentPolicy).where(
            and_(
                InvestmentPolicy.client_id == current_user.client_id,
                InvestmentPolicy.entity_id == entity_uuid,
                InvestmentPolicy.is_active == True,
            )
        )
        result = await db.execute(stmt)
        policy = result.scalar()

        if not policy:
            return {"policy": None}

        return {
            "policy": {
                "id": str(policy.id),
                "entity_id": str(policy.entity_id),
                "version": policy.version,
                "document_url": policy.document_path,
                "uploaded_by": str(policy.uploaded_by),
                "uploaded_at": policy.uploaded_at.isoformat(),
            }
        }
    else:
        stmt = select(InvestmentPolicy).where(
            and_(
                InvestmentPolicy.client_id == current_user.client_id,
                InvestmentPolicy.is_active == True,
            )
        )
        result = await db.execute(stmt)
        policies = result.scalars().all()

        policies_data = [
            {
                "id": str(p.id),
                "entity_id": str(p.entity_id),
                "version": p.version,
                "document_url": p.document_path,
                "uploaded_by": str(p.uploaded_by),
                "uploaded_at": p.uploaded_at.isoformat(),
            }
            for p in policies
        ]

        return {"policies": policies_data}


@router.post("/api/config/investment-policy", status_code=201)
async def upload_investment_policy(
    entity_id: str = Query(...),
    version: str = Query(...),
    file_content: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_INVESTMENTS)),
) -> dict:
    """POST /api/config/investment-policy - Upload investment policy."""
    from uuid import UUID as UUIDType

    user_id_uuid = UUIDType(current_user.user_id)
    entity_uuid = UUIDType(entity_id)

    stmt = select(InvestmentPolicy).where(
        and_(
            InvestmentPolicy.client_id == current_user.client_id,
            InvestmentPolicy.entity_id == entity_uuid,
            InvestmentPolicy.is_active == True,
        )
    )
    result = await db.execute(stmt)
    existing_policies = result.scalars().all()

    for policy in existing_policies:
        policy.is_active = False

    document_path = f"clients/{current_user.client_id}/policies/{version}.pdf"

    new_policy = InvestmentPolicy(
        client_id=current_user.client_id,
        entity_id=entity_uuid,
        version=version,
        document_path=document_path,
        uploaded_by=user_id_uuid,
    )
    db.add(new_policy)

    await write_audit_event(
        db=db,
        client_id=current_user.client_id,
        user_id=user_id_uuid,
        user_name=current_user.email,
        action="config.investment_policy_uploaded",
        entity_type="investment_policy",
        new_value={
            "entity_id": str(entity_id),
            "version": version,
        },
        ip_address=request.client.host if request and request.client else "0.0.0.0",
    )

    await db.commit()
    await db.refresh(new_policy)

    document_url = f"https://s3.us-east-1.amazonaws.com/core-cash-policies/{document_path}"

    return {
        "id": str(new_policy.id),
        "entity_id": str(new_policy.entity_id),
        "version": new_policy.version,
        "document_url": document_url,
        "uploaded_by": str(new_policy.uploaded_by),
        "uploaded_at": new_policy.uploaded_at.isoformat(),
    }


@router.get("/api/config/investment-cutoffs")
async def get_investment_cutoffs(
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """GET /api/config/investment-cutoffs - Get investment cutoffs."""
    stmt = select(InvestmentCutoff).where(
        InvestmentCutoff.client_id == current_user.client_id
    )
    result = await db.execute(stmt)
    cutoffs = result.scalars().all()

    cutoffs_data = []
    for c in cutoffs:
        entity_stmt = select(LegalEntity).where(LegalEntity.id == c.entity_id)
        entity_result = await db.execute(entity_stmt)
        entity = entity_result.scalar()

        account_name = None
        if c.investment_account_id:
            account_stmt = select(Account).where(Account.id == c.investment_account_id)
            account_result = await db.execute(account_stmt)
            account = account_result.scalar()
            account_name = account.account_name if account else None

        cutoffs_data.append({
            "entity_id": str(c.entity_id),
            "entity_name": entity.name if entity else None,
            "cutoff_time": str(c.cutoff_time),
            "timezone": c.timezone,
            "investment_account_id": str(c.investment_account_id) if c.investment_account_id else None,
            "investment_account_name": account_name,
        })

    return {"cutoffs": cutoffs_data}


@router.put("/api/config/investment-cutoffs/{entity_id}")
async def update_investment_cutoff(
    entity_id: str,
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_SYSTEM_CONFIG)),
) -> dict:
    """PUT /api/config/investment-cutoffs/{entity_id} - Update investment cutoff."""
    from uuid import UUID as UUIDType
    from datetime import time

    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(body.get("timezone", "America/New_York"))
    except Exception:
        raise HTTPException(status_code=422, detail="VALIDATION_INVALID_TIMEZONE")

    user_id_uuid = UUIDType(current_user.user_id)
    entity_uuid = UUIDType(entity_id)

    stmt = select(InvestmentCutoff).where(
        and_(
            InvestmentCutoff.client_id == current_user.client_id,
            InvestmentCutoff.entity_id == entity_uuid,
        )
    )
    result = await db.execute(stmt)
    cutoff = result.scalar()

    old_value = None
    if cutoff:
        old_value = {"cutoff_time": str(cutoff.cutoff_time)}

    cutoff_time_str = body.get("cutoff_time", "09:00")
    cutoff_time = datetime.strptime(cutoff_time_str, "%H:%M").time()

    if not cutoff:
        cutoff = InvestmentCutoff(
            client_id=current_user.client_id,
            entity_id=entity_uuid,
            cutoff_time=cutoff_time,
            timezone=body.get("timezone", "America/New_York"),
            investment_account_id=body.get("investment_account_id"),
            updated_by=user_id_uuid,
        )
        db.add(cutoff)
    else:
        cutoff.cutoff_time = cutoff_time
        cutoff.timezone = body.get("timezone", "America/New_York")
        cutoff.investment_account_id = body.get("investment_account_id")
        cutoff.updated_by = user_id_uuid

    await write_audit_event(
        db=db,
        client_id=current_user.client_id,
        user_id=user_id_uuid,
        user_name=current_user.email,
        action="config.investment_cutoff_updated",
        entity_type="investment_cutoff",
        old_value=old_value,
        new_value={"cutoff_time": cutoff_time_str},
        ip_address=request.client.host if request.client else "0.0.0.0",
    )

    await db.commit()
    await db.refresh(cutoff)

    entity_stmt = select(LegalEntity).where(LegalEntity.id == cutoff.entity_id)
    entity_result = await db.execute(entity_stmt)
    entity = entity_result.scalar()

    account_name = None
    if cutoff.investment_account_id:
        account_stmt = select(Account).where(Account.id == cutoff.investment_account_id)
        account_result = await db.execute(account_stmt)
        account = account_result.scalar()
        account_name = account.account_name if account else None

    return {
        "entity_id": str(cutoff.entity_id),
        "entity_name": entity.name if entity else None,
        "cutoff_time": str(cutoff.cutoff_time),
        "timezone": cutoff.timezone,
        "investment_account_id": str(cutoff.investment_account_id) if cutoff.investment_account_id else None,
        "investment_account_name": account_name,
    }


@router.get("/api/config/system")
async def get_system_config(
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """GET /api/config/system - Get system config."""
    stmt = select(SystemConfig).where(
        SystemConfig.client_id == current_user.client_id
    )
    result = await db.execute(stmt)
    configs = result.scalars().all()

    configs_data = [
        {
            "key": c.config_key,
            "value": c.config_val,
            "updated_by": str(c.updated_by) if c.updated_by else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in configs
    ]

    return {"config": configs_data}


@router.put("/api/config/system/{key}", status_code=200)
async def update_system_config(
    key: str,
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_SYSTEM_CONFIG)),
) -> dict:
    """PUT /api/config/system/{key} - Update system config."""
    from uuid import UUID as UUIDType

    allowed_keys = {
        "forecast_confidence_threshold",
        "warning_threshold_pct",
        "significant_outflow_pct",
    }

    if key not in allowed_keys:
        raise HTTPException(status_code=422, detail=f"Unknown config key: {key}")

    value = str(body.get("value", ""))

    try:
        val_int = int(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Value must be an integer")

    if key == "forecast_confidence_threshold":
        if not (0 <= val_int <= 100):
            raise HTTPException(status_code=422, detail="Value must be between 0 and 100")
    elif key == "warning_threshold_pct":
        if not (50 <= val_int <= 99):
            raise HTTPException(status_code=422, detail="Value must be between 50 and 99")
    elif key == "significant_outflow_pct":
        if not (1 <= val_int <= 50):
            raise HTTPException(status_code=422, detail="Value must be between 1 and 50")

    user_id_uuid = UUIDType(current_user.user_id)

    stmt = select(SystemConfig).where(
        and_(
            SystemConfig.client_id == current_user.client_id,
            SystemConfig.config_key == key,
        )
    )
    result = await db.execute(stmt)
    config = result.scalar()

    if config:
        config.config_val = value
        config.updated_by = user_id_uuid
    else:
        config = SystemConfig(
            client_id=current_user.client_id,
            config_key=key,
            config_val=value,
            updated_by=user_id_uuid,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)

    return {
        "key": config.config_key,
        "value": config.config_val,
        "updated_by": str(config.updated_by) if config.updated_by else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
