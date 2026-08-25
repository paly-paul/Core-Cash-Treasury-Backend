from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from core_cash_shared.schemas.auth import UserClaims
from core_cash_shared.enums import Permission
from app.database import get_db
from app.models.account import Account
from app.models.bank import Bank

router = APIRouter()


class AccountResponse:
    def __init__(self, account: Account, bank_name: Optional[str] = None):
        self.account_id = str(account.id)
        self.account_name = account.account_name
        self.bank_name = bank_name
        self.entity_id = str(account.entity_id)
        self.currency = account.currency
        self.min_threshold = float(account.min_threshold)
        self.restricted_flag = account.restricted_flag
        self.od_limit = float(account.od_limit) if account.od_limit else None
        self.od_utilised_amount = (
            float(account.od_utilised_amount) if account.od_utilised_amount else None
        )
        self.refresh_frequency = account.refresh_frequency
        self.include_in_cash_position = account.include_in_cash_position
        self.is_active = account.is_active

    def dict(self):
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "bank_name": self.bank_name,
            "entity_id": self.entity_id,
            "currency": self.currency,
            "min_threshold": self.min_threshold,
            "restricted_flag": self.restricted_flag,
            "od_limit": self.od_limit,
            "od_utilised_amount": self.od_utilised_amount,
            "refresh_frequency": self.refresh_frequency,
            "include_in_cash_position": self.include_in_cash_position,
            "is_active": self.is_active,
        }


@router.get("/api/accounts")
async def list_accounts(
    entity_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """GET /api/accounts - List accounts for current client."""
    stmt = select(Account).where(Account.client_id == current_user.client_id)

    if entity_id:
        stmt = stmt.where(Account.entity_id == UUID(entity_id))

    if not include_inactive:
        stmt = stmt.where(Account.is_active == True)

    result = await db.execute(stmt)
    accounts = result.scalars().all()

    # Join with bank names
    accounts_data = []
    for account in accounts:
        bank_name = None
        if account.bank_id:
            bank_stmt = select(Bank).where(Bank.id == account.bank_id)
            bank_result = await db.execute(bank_stmt)
            bank = bank_result.scalar()
            bank_name = bank.name if bank else None

        accounts_data.append(AccountResponse(account, bank_name).dict())

    return {"accounts": accounts_data}


@router.get("/api/accounts/{account_id}")
async def get_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """GET /api/accounts/{account_id} - Get single account."""
    stmt = select(Account).where(
        (Account.id == UUID(account_id)) & (Account.client_id == current_user.client_id)
    )
    result = await db.execute(stmt)
    account = result.scalar()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    bank_name = None
    if account.bank_id:
        bank_stmt = select(Bank).where(Bank.id == account.bank_id)
        bank_result = await db.execute(bank_stmt)
        bank = bank_result.scalar()
        bank_name = bank.name if bank else None

    return AccountResponse(account, bank_name).dict()


@router.post("/api/accounts", status_code=201)
async def create_account(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_INVESTMENTS)),
) -> dict:
    """POST /api/accounts - Create new account."""
    account = Account(
        client_id=current_user.client_id,
        entity_id=UUID(body["entity_id"]),
        bank_id=UUID(body.get("bank_id")) if body.get("bank_id") else None,
        account_name=body["account_name"],
        currency=body["currency"],
        min_threshold=Decimal(str(body.get("min_threshold", 0))),
        restricted_flag=body.get("restricted_flag", False),
        od_limit=Decimal(str(body["od_limit"])) if body.get("od_limit") else None,
        refresh_frequency=body.get("refresh_frequency", "Daily"),
        include_in_cash_position=body.get("include_in_cash_position", True),
        is_active=True,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    bank_name = None
    if account.bank_id:
        bank_stmt = select(Bank).where(Bank.id == account.bank_id)
        bank_result = await db.execute(bank_stmt)
        bank = bank_result.scalar()
        bank_name = bank.name if bank else None

    return AccountResponse(account, bank_name).dict()


@router.put("/api/accounts/{account_id}")
async def update_account(
    account_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_INVESTMENTS)),
) -> dict:
    """PUT /api/accounts/{account_id} - Update account (patch semantics)."""
    stmt = select(Account).where(
        (Account.id == UUID(account_id)) & (Account.client_id == current_user.client_id)
    )
    result = await db.execute(stmt)
    account = result.scalar()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Update mutable fields
    for field in [
        "account_name",
        "currency",
        "min_threshold",
        "restricted_flag",
        "od_limit",
        "refresh_frequency",
        "include_in_cash_position",
    ]:
        if field in body:
            if field in ["min_threshold", "od_limit"]:
                setattr(account, field, Decimal(str(body[field])))
            else:
                setattr(account, field, body[field])

    await db.commit()
    await db.refresh(account)

    bank_name = None
    if account.bank_id:
        bank_stmt = select(Bank).where(Bank.id == account.bank_id)
        bank_result = await db.execute(bank_stmt)
        bank = bank_result.scalar()
        bank_name = bank.name if bank else None

    return AccountResponse(account, bank_name).dict()
