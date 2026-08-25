"""
Recommendation endpoints: request, poll, list, approve, reject, override.
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4, UUID
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
from app.services.recommendation_service import (
    get_recommendation_result,
    approve_recommendation,
    reject_recommendation,
    override_recommendation,
    get_pending_approvals_count,
    find_recommendation_by_id,
)
from core_cash_shared import JobStatus as JobStatusEnum, JobType
from core_cash_shared.schemas.jobs import JobEnvelope

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Request Models
# ============================================================================


class RecommendationRequestBody(BaseModel):
    cash_position_date: Optional[str] = None
    policy_id: Optional[str] = None


class ApproveRequestBody(BaseModel):
    notes: str


class RejectRequestBody(BaseModel):
    reason: str


class OverrideRequestBody(BaseModel):
    action_taken: str
    notes: str


# ============================================================================
# POST /api/recommendations/request
# ============================================================================


@router.post("/api/recommendations/request", status_code=202)
async def request_recommendation(
    body: RecommendationRequestBody,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_ASSUMPTIONS)),
) -> dict:
    """
    Publish a recommendation job to SQS/in-process queue.
    Returns 202 with request_id.
    """
    from app.jobs.in_process import InProcessJobPublisher

    job_id = str(uuid4())
    now = datetime.utcnow()

    # Create JobEnvelope
    envelope = JobEnvelope(
        job_id=job_id,
        job_type=JobType.ACTION_RECOMMENDATION,
        client_id=str(current_user.client_id),
        user_id=str(current_user.user_id),
        requested_at=now,
        payload={
            "cash_position_date": body.cash_position_date or datetime.utcnow().date().isoformat(),
            "policy_id": body.policy_id or "policy_default",
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

    # Publish job
    try:
        publisher = InProcessJobPublisher()
        await publisher.publish(envelope)
    except Exception as exc:
        logger.error(f"Failed to publish recommendation job: {exc}")
        raise HTTPException(
            status_code=503,
            detail={"code": "AGENT_ERROR", "message": "Recommendation job could not be queued. Please retry."},
        )

    return {
        "request_id": job_id,
        "status": JobStatusEnum.QUEUED.value,
        "queued_at": now.isoformat() + "Z",
        "estimated_completion": "30–60 seconds",
    }


# ============================================================================
# GET /api/recommendations/{request_id}
# ============================================================================


@router.get("/api/recommendations/{request_id}")
async def get_recommendation_status(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """
    Poll for recommendation result. Returns job status or full result with reasoning_trace.
    """
    # Query job_status
    stmt = select(JobStatus).where(
        (JobStatus.job_id == request_id) & (JobStatus.client_id == current_user.client_id)
    )
    result = await db.execute(stmt)
    job = result.scalar()

    if not job:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Recommendation job not found"},
        )

    # Pending or processing
    if job.status in [JobStatusEnum.QUEUED.value, "processing"]:
        return {
            "request_id": str(job.job_id),
            "status": job.status,
            "queued_at": job.requested_at.isoformat() + "Z",
        }

    # Failed
    if job.status == JobStatusEnum.FAILED.value:
        return {
            "request_id": str(job.job_id),
            "status": job.status,
            "error": job.error_message or "Agent processing failed. Please retry.",
        }

    # Completed
    if job.status == JobStatusEnum.COMPLETED.value and job.result_id:
        try:
            rec_doc = await get_recommendation_result(mongo_db, job.result_id)

            # Static mock reasoning_trace
            # TODO: wire real timing from AgentState in Session 12
            reasoning_trace = [
                {"step": 1, "agent": "daily_cash", "status": "complete", "duration_ms": 220},
                {"step": 2, "agent": "liquidity_risk", "status": "complete", "duration_ms": 180},
                {"step": 3, "agent": "policy_check", "status": "complete", "duration_ms": 95},
                {"step": 4, "agent": "recommendation", "status": "complete", "duration_ms": 9200},
            ]

            return {
                "request_id": str(job.job_id),
                "status": job.status,
                "run_id": job.result_id,
                "generated_at": rec_doc.get("created_at", datetime.utcnow()).isoformat() + "Z",
                "recommendation_count": rec_doc.get("recommendation_count", 0),
                "recommendations": rec_doc.get("recommendations", []),
                "reasoning_trace": reasoning_trace,
            }
        except Exception as exc:
            logger.error(f"Failed to retrieve recommendation result: {exc}")
            raise HTTPException(
                status_code=500,
                detail={"code": "INTERNAL_ERROR", "message": "Failed to retrieve recommendation result"},
            )

    raise HTTPException(
        status_code=500,
        detail={"code": "INTERNAL_ERROR", "message": "Unexpected job status"},
    )


# ============================================================================
# GET /api/recommendations
# ============================================================================


@router.get("/api/recommendations")
async def list_recommendations(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """
    List all recommendation runs for the client (paginated).
    Filters by status if provided.
    Returns summary items with pending_approvals count.
    """
    # Query job_status
    stmt = select(JobStatus).where(JobStatus.client_id == current_user.client_id)

    if status:
        stmt = stmt.where(JobStatus.status == status)

    stmt = stmt.order_by(JobStatus.requested_at.desc())
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    # Paginate
    total = len(jobs)
    start = (page - 1) * page_size
    end = start + page_size
    paginated_jobs = jobs[start:end]

    # For each completed job, fetch pending_approvals count from MongoDB
    recommendations = []
    for job in paginated_jobs:
        item = {
            "request_id": str(job.job_id),
            "status": job.status,
            "generated_at": job.completed_at.isoformat() + "Z" if job.completed_at else None,
            "recommendation_count": 0,
            "pending_approvals": 0,
        }

        if job.status == JobStatusEnum.COMPLETED.value and job.result_id:
            try:
                pending_count = await get_pending_approvals_count(mongo_db, job.result_id)
                rec_doc = await get_recommendation_result(mongo_db, job.result_id)
                item["recommendation_count"] = rec_doc.get("recommendation_count", 0)
                item["pending_approvals"] = pending_count
            except Exception as exc:
                logger.warning(f"Failed to get pending approvals for {job.result_id}: {exc}")

        recommendations.append(item)

    return {
        "recommendations": recommendations,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ============================================================================
# POST /api/recommendations/{id}/approve
# ============================================================================


@router.post("/api/recommendations/{recommendation_id}/approve")
async def approve_recommendation_endpoint(
    recommendation_id: str,
    body: ApproveRequestBody,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
    current_user: UserClaims = Depends(require_permission(Permission.APPROVE_RECOMMENDATIONS)),
) -> dict:
    """
    Approve a recommendation item.
    Record only — no autonomous action initiated.
    """
    try:
        # Update MongoDB
        updated_rec = await approve_recommendation(
            mongo_db,
            str(current_user.client_id),
            recommendation_id,
            str(current_user.user_id),
            body.notes,
        )
    except ValueError as exc:
        if "already been actioned" in str(exc):
            raise HTTPException(
                status_code=409,
                detail={"code": "VALIDATION_ERROR", "message": "Recommendation has already been actioned."},
            )
        else:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Recommendation not found"},
            )

    # Write audit event (non-blocking)
    try:
        await write_audit_event(
            db,
            current_user.client_id,
            UUID(current_user.user_id),
            None,  # user_name provided by middleware
            "recommendation.approved",
            entity_type="recommendation",
            entity_id=recommendation_id,
            old_value={"approval_status": "Pending"},
            new_value={"approval_status": "Approved", "notes": body.notes},
        )
    except Exception as exc:
        logger.error(f"Audit write failed for recommendation.approved: {exc}")

    return {
        "id": updated_rec.get("id"),
        "approval_status": updated_rec.get("approval_status"),
        "approved_by": updated_rec.get("approved_by"),
        "approved_at": updated_rec.get("approved_at", datetime.utcnow()).isoformat() + "Z",
        "notes": updated_rec.get("notes"),
    }


# ============================================================================
# POST /api/recommendations/{id}/reject
# ============================================================================


@router.post("/api/recommendations/{recommendation_id}/reject")
async def reject_recommendation_endpoint(
    recommendation_id: str,
    body: RejectRequestBody,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
    current_user: UserClaims = Depends(require_permission(Permission.APPROVE_RECOMMENDATIONS)),
) -> dict:
    """
    Reject a recommendation item.
    """
    try:
        # Update MongoDB
        updated_rec = await reject_recommendation(
            mongo_db,
            str(current_user.client_id),
            recommendation_id,
            str(current_user.user_id),
            body.reason,
        )
    except ValueError as exc:
        if "already been actioned" in str(exc):
            raise HTTPException(
                status_code=409,
                detail={"code": "VALIDATION_ERROR", "message": "Recommendation has already been actioned."},
            )
        else:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Recommendation not found"},
            )

    # Write audit event (non-blocking)
    try:
        await write_audit_event(
            db,
            current_user.client_id,
            UUID(current_user.user_id),
            None,
            "recommendation.rejected",
            entity_type="recommendation",
            entity_id=recommendation_id,
            old_value={"approval_status": "Pending"},
            new_value={"approval_status": "Rejected", "rejection_reason": body.reason},
        )
    except Exception as exc:
        logger.error(f"Audit write failed for recommendation.rejected: {exc}")

    return {
        "id": updated_rec.get("id"),
        "approval_status": updated_rec.get("approval_status"),
        "rejected_by": updated_rec.get("rejected_by"),
        "rejected_at": updated_rec.get("rejected_at", datetime.utcnow()).isoformat() + "Z",
        "reason": updated_rec.get("rejection_reason"),
    }


# ============================================================================
# POST /api/recommendations/{id}/override
# ============================================================================


@router.post("/api/recommendations/{recommendation_id}/override")
async def override_recommendation_endpoint(
    recommendation_id: str,
    body: OverrideRequestBody,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
    current_user: UserClaims = Depends(require_permission(Permission.APPROVE_RECOMMENDATIONS)),
) -> dict:
    """
    Override a recommendation with manual action taken.
    """
    try:
        # Update MongoDB
        updated_rec = await override_recommendation(
            mongo_db,
            str(current_user.client_id),
            recommendation_id,
            str(current_user.user_id),
            body.action_taken,
            body.notes,
        )
    except ValueError as exc:
        if "already been actioned" in str(exc):
            raise HTTPException(
                status_code=409,
                detail={"code": "VALIDATION_ERROR", "message": "Recommendation has already been actioned."},
            )
        else:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Recommendation not found"},
            )

    # Write audit event (non-blocking)
    try:
        await write_audit_event(
            db,
            current_user.client_id,
            UUID(current_user.user_id),
            None,
            "recommendation.overridden",
            entity_type="recommendation",
            entity_id=recommendation_id,
            old_value={"approval_status": "Pending"},
            new_value={"approval_status": "Overridden", "action_taken": body.action_taken},
        )
    except Exception as exc:
        logger.error(f"Audit write failed for recommendation.overridden: {exc}")

    return {
        "id": updated_rec.get("id"),
        "approval_status": updated_rec.get("approval_status"),
        "overridden_by": updated_rec.get("overridden_by"),
        "overridden_at": updated_rec.get("overridden_at", datetime.utcnow()).isoformat() + "Z",
        "action_taken": updated_rec.get("action_taken"),
        "notes": updated_rec.get("notes"),
    }
