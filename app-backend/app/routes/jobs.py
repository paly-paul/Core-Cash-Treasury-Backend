from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import UserModel
from app.database import get_db
from app.models.job_status import JobStatus
from app.mongo.client import get_mongo_db
from core_cash_shared import JobStatus as JobStatusEnum, JobType
from core_cash_shared.error_codes import JOB_NOT_FOUND
from core_cash_shared.schemas.jobs import JobEnvelope, JobStatusResponse

router = APIRouter()


@router.post("/api/cash-position/request", status_code=202)
async def request_cash_position(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict:
    """
    POST /api/cash-position/request
    Initiate a Daily Cash Position Agent run.
    Returns HTTP 202 with request_id (job_id).
    """
    from app.jobs.in_process import InProcessJobPublisher

    job_id = str(uuid4())
    now = datetime.utcnow()

    # Create JobEnvelope
    envelope = JobEnvelope(
        job_id=job_id,
        job_type=JobType.CASH_POSITION,
        client_id=str(current_user.client_id),
        user_id=str(current_user.id),
        requested_at=now,
        payload={},
    )

    # Create job_status record
    job_status = JobStatus(
        client_id=current_user.client_id,
        job_id=envelope.job_id,
        job_type=envelope.job_type.value,
        status=JobStatusEnum.QUEUED.value,
        requested_by=current_user.id,
        requested_at=now,
    )
    db.add(job_status)
    await db.commit()

    # Publish job
    publisher = InProcessJobPublisher()
    await publisher.publish(envelope)

    return {
        "request_id": job_id,
        "status": JobStatusEnum.QUEUED.value,
        "job_type": JobType.CASH_POSITION.value,
    }


@router.get("/api/jobs/{request_id}")
async def get_job_status(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> JobStatusResponse:
    """
    GET /api/jobs/{request_id}
    Poll for job status and result.
    """
    from sqlalchemy import select

    stmt = select(JobStatus).where(
        (JobStatus.job_id == request_id) & (JobStatus.client_id == current_user.client_id)
    )
    result = await db.execute(stmt)
    job = result.scalar()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": JOB_NOT_FOUND, "message": "Job not found"},
        )

    return JobStatusResponse(
        request_id=str(job.job_id),
        status=job.status,
        job_type=job.job_type,
        requested_at=job.requested_at,
        completed_at=job.completed_at,
        result_id=job.result_id,
        error=job.error_message,
    )


@router.get("/api/cash-position/{result_id}")
async def get_cash_position_result(
    result_id: str,
    current_user: UserModel = Depends(get_current_user),
):
    """
    GET /api/cash-position/{result_id}
    Retrieve Agent 1 output document from MongoDB.
    """
    from bson import ObjectId

    try:
        doc_id = ObjectId(result_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid result_id format")

    mongo_db = get_mongo_db()
    collection = mongo_db["agent_runs"]
    doc = await collection.find_one(
        {"_id": doc_id, "client_id": str(current_user.client_id)}
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Result not found")

    doc["_id"] = str(doc["_id"])
    return doc
