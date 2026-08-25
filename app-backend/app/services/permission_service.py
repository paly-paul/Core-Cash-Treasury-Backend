from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from core_cash_shared.enums import Permission
from app.models.user_permission import UserPermission
import time
import structlog

logger = structlog.get_logger()

_PERMISSION_CACHE: dict[str, tuple[set[Permission], float]] = {}
_CACHE_TTL = 300  # 5 minutes


def invalidate_permission_cache(client_id: str, user_id: str) -> None:
    _PERMISSION_CACHE.pop(f"{client_id}:{user_id}", None)


async def load_user_permissions(
    db: AsyncSession,
    client_id: str,
    user_id: str,
) -> set[Permission]:
    """
    Load all granted permissions for a user from user_permissions table.
    No role defaults — only explicit grants (minus explicit revokes).
    Cached for 5 minutes per user.
    """
    key = f"{client_id}:{user_id}"
    entry = _PERMISSION_CACHE.get(key)
    if entry and entry[1] > time.monotonic():
        return entry[0]

    result = await db.execute(
        select(UserPermission).where(
            UserPermission.client_id == client_id,
            UserPermission.user_id == user_id,
            or_(
                UserPermission.expires_at == None,
                UserPermission.expires_at > func.now()
            )
        )
    )
    rows = result.scalars().all()
    permissions: set[Permission] = set()
    revoked: set[str] = set()

    # Collect revokes first, then apply grants minus revokes
    for row in rows:
        if row.grant_type == "revoke":
            revoked.add(row.permission)

    for row in rows:
        if row.grant_type == "grant" and row.permission not in revoked:
            try:
                permissions.add(Permission(row.permission))
            except ValueError:
                logger.warning("unknown_permission", value=row.permission)

    _PERMISSION_CACHE[key] = (permissions, time.monotonic() + _CACHE_TTL)
    return permissions
