from sqlalchemy import select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.models import UserModel
from app.database import get_db
from app.models.legal_entity import LegalEntity
from app.models.account import Account

router = APIRouter()


@router.get("/api/metadata/entities")
async def get_entities(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict:
    """GET /api/metadata/entities - Get entities for client."""
    stmt = select(LegalEntity).where(
        LegalEntity.client_id == current_user.client_id
    )
    result = await db.execute(stmt)
    entities = result.scalars().all()

    entities_data = [
        {
            "id": str(e.id),
            "name": e.name,
            "base_currency": e.base_currency,
        }
        for e in entities
    ]

    return {"entities": entities_data}


@router.get("/api/metadata/currencies")
async def get_currencies(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict:
    """GET /api/metadata/currencies - Get currencies for client."""
    stmt = select(distinct(Account.currency)).where(
        Account.client_id == current_user.client_id
    )
    result = await db.execute(stmt)
    currencies = sorted([c for c in result.scalars().all() if c])

    return {"currencies": currencies}
