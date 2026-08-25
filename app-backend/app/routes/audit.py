import csv
import io
from datetime import datetime, date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from core_cash_shared.schemas.auth import UserClaims
from core_cash_shared.enums import Permission
from app.database import get_db
from app.models.audit_log import AuditLog

router = APIRouter()


@router.get("/api/audit-log")
async def get_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    entity_type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.VIEW_AUDIT_LOG)),
) -> dict:
    """GET /api/audit-log - Get audit log entries for client."""
    stmt = select(AuditLog).where(AuditLog.client_id == current_user.client_id)

    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)

    if user_id:
        try:
            user_uuid = UUID(user_id)
            stmt = stmt.where(AuditLog.user_id == user_uuid)
        except ValueError:
            pass

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            stmt = stmt.where(AuditLog.created_at >= date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            stmt = stmt.where(AuditLog.created_at < datetime.combine(date_to_obj, datetime.max.time()))
        except ValueError:
            pass

    stmt = stmt.order_by(AuditLog.created_at.desc())

    result = await db.execute(stmt)
    all_entries = result.scalars().all()

    total = len(all_entries)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    entries = all_entries[start_idx:end_idx]

    entries_data = [
        {
            "id": str(e.id),
            "client_id": str(e.client_id),
            "user_id": str(e.user_id) if e.user_id else None,
            "user_name": e.user_name,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "old_value": e.old_value,
            "new_value": e.new_value,
            "ip_address": str(e.ip_address) if e.ip_address else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]

    return {
        "entries": entries_data,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/api/audit-log/export")
async def export_audit_log(
    format: str = Query("csv"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.VIEW_AUDIT_LOG)),
):
    """GET /api/audit-log/export - Export audit log as CSV or PDF."""
    if format == "pdf":
        raise HTTPException(status_code=501, detail="PDF export not yet available")

    if format != "csv":
        raise HTTPException(status_code=400, detail="Invalid format. Supported: csv, pdf")

    stmt = select(AuditLog).where(AuditLog.client_id == current_user.client_id)

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            stmt = stmt.where(AuditLog.created_at >= date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            stmt = stmt.where(AuditLog.created_at < datetime.combine(date_to_obj, datetime.max.time()))
        except ValueError:
            pass

    stmt = stmt.order_by(AuditLog.created_at.desc())

    result = await db.execute(stmt)
    entries = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID", "Client ID", "User ID", "User Name", "Action", "Entity Type", "Entity ID",
        "Old Value", "New Value", "IP Address", "Created At"
    ])

    for e in entries:
        writer.writerow([
            str(e.id),
            str(e.client_id),
            str(e.user_id) if e.user_id else "",
            e.user_name or "",
            e.action,
            e.entity_type or "",
            e.entity_id or "",
            str(e.old_value) if e.old_value else "",
            str(e.new_value) if e.new_value else "",
            str(e.ip_address) if e.ip_address else "",
            e.created_at.isoformat() if e.created_at else "",
        ])

    return {
        "type": "text/csv",
        "filename": "audit-log-export.csv",
        "content": output.getvalue(),
    }
