import logging
from typing import Optional, Any, Dict
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def write_audit_event(
    db: AsyncSession,
    client_id: UUID,
    user_id: Optional[UUID],
    user_name: Optional[str],
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    old_value: Optional[Dict[str, Any]] = None,
    new_value: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> None:
    """
    Write one audit event. Non-blocking — caller must not depend on this succeeding.
    If the write fails for any reason, log the error and return — never raise.
    """
    try:
        entry = AuditLog(
            client_id=client_id,
            user_id=user_id,
            user_name=user_name or "System",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address or "0.0.0.0",
        )
        db.add(entry)
        await db.commit()
    except Exception as exc:
        logger.error(f"Audit write failed for action={action}: {exc}", exc_info=True)
