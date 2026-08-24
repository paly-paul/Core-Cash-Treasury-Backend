from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import UserModel
from app.database import get_db
from app.models.job_status import JobStatus
from app.mongo.client import get_mongo_db
from core_cash_shared import JobStatus as JobStatusEnum, JobType

router = APIRouter()


@router.post("/api/liquidity-risk/request", status_code=202)
async def request_liquidity_risk(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict:
    """
    POST /api/liquidity-risk/request
    Initiate a Liquidity Risk Agent run.
    Returns HTTP 202 with request_id (job_id).
    """
    from app.jobs.in_process import InProcessJobPublisher
    from core_cash_shared.schemas.jobs import JobEnvelope

    job_id = str(uuid4())
    now = datetime.utcnow()

    # Create JobEnvelope
    envelope = JobEnvelope(
        job_id=job_id,
        job_type=JobType.LIQUIDITY_RISK,
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
        "queued_at": now.isoformat() + "Z",
    }


@router.get("/api/liquidity-risk/{request_id}")
async def get_liquidity_risk_status(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """
    GET /api/liquidity-risk/{request_id}
    Poll for job status and result.
    When completed, returns full Agent 3 output.
    """
    from bson import ObjectId

    stmt = select(JobStatus).where(
        (JobStatus.job_id == request_id) & (JobStatus.client_id == current_user.client_id)
    )
    result = await db.execute(stmt)
    job = result.scalar()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": "Job not found"},
        )

    # If job is still pending, return status only
    if job.status != JobStatusEnum.COMPLETED.value:
        return {
            "request_id": str(job.job_id),
            "status": job.status,
            "queued_at": job.requested_at.isoformat() + "Z" if job.requested_at else None,
        }

    # If job is completed, retrieve result from MongoDB
    if job.result_id:
        try:
            doc_id = ObjectId(job.result_id)
        except Exception:
            raise HTTPException(status_code=404, detail="Invalid result_id format")

        mongo_db = get_mongo_db()
        collection = mongo_db["agent_runs"]
        doc = await collection.find_one(
            {"_id": doc_id, "client_id": str(current_user.client_id)}
        )

        if doc:
            doc["_id"] = str(doc["_id"])
            return doc

    raise HTTPException(status_code=404, detail="Result not found")


@router.get("/api/liquidity-risk/current")
async def get_current_liquidity_risk(
    current_user: UserModel = Depends(get_current_user),
):
    """
    GET /api/liquidity-risk/current
    Retrieve the most recent completed Liquidity Risk assessment.
    Synchronous — no polling needed.
    """
    mongo_db = get_mongo_db()
    collection = mongo_db["agent_runs"]
    doc = await collection.find_one(
        {"client_id": str(current_user.client_id), "agent": "liquidity_risk"},
        sort=[("as_of", -1)],
    )

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "No liquidity risk assessment available. Request one via POST /api/liquidity-risk/request.",
                }
            },
        )

    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/api/liquidity-risk/alerts")
async def get_liquidity_risk_alerts(
    current_user: UserModel = Depends(get_current_user),
):
    """
    GET /api/liquidity-risk/alerts
    Retrieve critical alerts from the most recent Liquidity Risk assessment.
    Returns only high severity subset: risk_level, critical_breaches, forecast_shortfall_days.
    """
    mongo_db = get_mongo_db()
    collection = mongo_db["agent_runs"]
    doc = await collection.find_one(
        {"client_id": str(current_user.client_id), "agent": "liquidity_risk"},
        sort=[("as_of", -1)],
    )

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "No liquidity risk assessment available.",
                }
            },
        )

    return {
        "as_of": doc.get("as_of"),
        "risk_level": doc.get("risk_level"),
        "critical_breaches": doc.get("active_breaches", []),
        "forecast_shortfall_days": doc.get("forecast_shortfall_days", []),
    }
