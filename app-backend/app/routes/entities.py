from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import UserModel
from app.database import get_db
from app.models.legal_entity import LegalEntity

router = APIRouter()


@router.get("/api/entities")
async def list_entities(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict:
    """GET /api/entities - List legal entities for current client."""
    stmt = select(LegalEntity).where(LegalEntity.client_id == current_user.client_id)
    result = await db.execute(stmt)
    entities = result.scalars().all()

    entities_data = [
        {
            "entity_id": str(e.id),
            "name": e.name,
            "base_currency": e.base_currency,
            "country_code": e.country_code,
        }
        for e in entities
    ]

    return {"entities": entities_data}
