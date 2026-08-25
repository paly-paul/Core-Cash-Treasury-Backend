"""
Variance explanation endpoints: request, poll, current.
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from core_cash_shared.schemas.auth import UserClaims
from core_cash_shared.enums import Permission
from app.database import get_db
from app.models.job_status import JobStatus
from app.mongo.client import get_mongo_db
from app.services.audit_service import write_audit_event
from core_cash_shared import JobStatus as JobStatusEnum, JobType
from core_cash_shared.schemas.jobs import JobEnvelope

logger = logging.getLogger(__name__)
router = APIRouter()


class VarianceRequestBody(BaseModel):
    entity_id: str
    analysis_date: Optional[str] = None


@router.post("/request", status_code=202)
async def request_variance_explanation(
    body: VarianceRequestBody,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_ASSUMPTIONS)),
) -> dict:
    """
    Publish a variance explanation job to SQS/in-process queue.
    Returns 202 with request_id.
    """
    from app.jobs.in_process import InProcessJobPublisher

    # Validate entity_id belongs to caller's client
    from app.models.entity import Entity

    result = await db.execute(
        select(Entity).where(
            Entity.id == body.entity_id, Entity.client_id == current_user.client_id
        )
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    job_id = str(uuid4())
    now = datetime.utcnow()

    # Create JobEnvelope
    envelope = JobEnvelope(
        job_id=job_id,
        job_type=JobType.VARIANCE_EXPLANATION,
        client_id=str(current_user.client_id),
        user_id=str(current_user.user_id),
        requested_at=now,
        payload={
            "entity_id": body.entity_id,
            "analysis_date": body.analysis_date,
        },
    )

    # Create job_status record
    job_status = JobStatus(
        client_id=current_user.client_id,
        job_id=envelope.job_id,
        job_type=envelope.job_type.value,
        status=JobStatusEnum.QUEUED.value,
        requested_by=current_user.user_id,
        requested_at=now,
    )
    db.add(job_status)
    await db.commit()

    # Write audit event
    await write_audit_event(
        db=db,
        client_id=current_user.client_id,
        user_id=current_user.user_id,
        action="variance_explanation.requested",
        entity_type="variance_explanation",
        entity_id=job_id,
        old_value=None,
        new_value={"status": "Pending"},
    )

    # Publish job
    publisher = InProcessJobPublisher()
    await publisher.publish(envelope)

    return {
        "request_id": job_id,
        "status": "Pending",
        "message": "Variance explanation job queued. Poll /api/forecast/variance/{request_id} for status.",
    }


@router.get("/{variance_id}")
async def get_variance_explanation(
    variance_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.VIEW_VARIANCE)),
) -> dict:
    """
    Poll for variance explanation result.
    """
    mongo = get_mongo_db()

    # Look up job_status
    result = await db.execute(
        select(JobStatus).where(
            JobStatus.job_id == variance_id,
            JobStatus.client_id == current_user.client_id,
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Variance not found")

    if job.status == JobStatusEnum.QUEUED.value or job.status == JobStatusEnum.PROCESSING.value:
        return {"status": job.status, "variance_id": variance_id}

    if job.status == JobStatusEnum.FAILED.value:
        return {
            "status": "Failed",
            "variance_id": variance_id,
            "error": job.error or "Unknown error",
        }

    if job.status == JobStatusEnum.COMPLETED.value:
        # Read from MongoDB
        collection = mongo["variance_explanations"]
        doc = await collection.find_one(
            {"variance_id": variance_id, "client_id": current_user.client_id}
        )

        if doc:
            # Strip internal fields
            doc.pop("_id", None)
            doc.pop("client_id", None)
            return doc
        else:
            raise HTTPException(status_code=404, detail="Variance result not found")

    raise HTTPException(status_code=500, detail="Unknown job status")


@router.get("/current")
async def get_current_variance_explanation(
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.VIEW_VARIANCE)),
) -> dict:
    """
    Get latest variance explanation for an entity.
    Query parameter: entity_id (required)
    """
    # Validate entity_id belongs to caller's client
    from app.models.entity import Entity

    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id, Entity.client_id == current_user.client_id
        )
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    mongo = get_mongo_db()
    collection = mongo["variance_explanations"]

    doc = await collection.find_one(
        {
            "client_id": str(current_user.client_id),
            "entity_id": entity_id,
            "data_status": {"$ne": "unavailable"},
        },
        sort=[("computed_at", -1)],
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="No variance explanation available for this entity.",
        )

    # Strip internal fields
    doc.pop("_id", None)
    doc.pop("client_id", None)
    return doc
