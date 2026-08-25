"""
Forecast endpoints: assumptions CRUD (live), forecast request/poll (live but blocked on calculation).
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from uuid import uuid4
import logging

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from core_cash_shared.schemas.auth import UserClaims
from core_cash_shared.enums import Permission
from app.database import get_db
from app.models.manual_assumption import ManualAssumption
from app.models.legal_entity import LegalEntity
from app.models.job_status import JobStatus
from app.models.system_config import SystemConfig
from app.mongo.client import get_mongo_db
from app.services.audit_service import write_audit_event
from core_cash_shared import JobStatus as JobStatusEnum, JobType
from core_cash_shared.schemas.jobs import JobEnvelope

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Request Models
# ============================================================================


class AssumptionCreateBody(BaseModel):
    entity_id: str
    currency: str
    direction: str
    amount: float
    date: str
    category: str
    description: str
    confidence_pct: int


class AssumptionUpdateBody(BaseModel):
    entity_id: str
    currency: str
    direction: str
    amount: float
    date: str
    category: str
    description: str
    confidence_pct: int


class ForecastRequestBody(BaseModel):
    horizon_days: int = 7
    cash_position_date: Optional[str] = None
    policy_id: Optional[str] = None


# ============================================================================
# Helpers
# ============================================================================


async def get_forecast_confidence_threshold(db: AsyncSession, client_id) -> int:
    """Read forecast_confidence_threshold from system_config. Default 50."""
    stmt = select(SystemConfig).where(
        and_(
            SystemConfig.client_id == client_id,
            SystemConfig.config_key == "forecast_confidence_threshold",
        )
    )
    result = await db.execute(stmt)
    config = result.scalar()
    if config:
        try:
            return int(config.config_val)
        except (ValueError, TypeError):
            return 50
    return 50


def derive_included_in_forecast(confidence_pct: Decimal, threshold: int) -> bool:
    """Derive included_in_forecast based on confidence_pct >= threshold."""
    if confidence_pct is None:
        return False
    try:
        conf_val = float(confidence_pct)
        return conf_val >= threshold
    except (ValueError, TypeError):
        return False


async def get_entity_name(db: AsyncSession, entity_id) -> Optional[str]:
    """Get entity name from legal_entity table."""
    stmt = select(LegalEntity).where(LegalEntity.id == entity_id)
    result = await db.execute(stmt)
    entity = result.scalar()
    return entity.name if entity else None


async def publish_forecast_job(
    db: AsyncSession,
    client_id,
    current_user: UserModel,
) -> None:
    """Publish a forecast job. Non-blocking — log and continue if publish fails."""
    from app.jobs.in_process import InProcessJobPublisher

    try:
        job_id = str(uuid4())
        now = datetime.utcnow()

        envelope = JobEnvelope(
            job_id=job_id,
            job_type=JobType.FORECAST,
            client_id=str(client_id),
            user_id=str(current_user.user_id),
            requested_at=now,
            payload={
                "triggered_by": "assumption_change",
                "horizon_days": 7,
            },
        )

        job_status = JobStatus(
            client_id=client_id,
            job_id=envelope.job_id,
            job_type=envelope.job_type.value,
            status=JobStatusEnum.QUEUED.value,
            requested_by=current_user.user_id,
            requested_at=now,
        )
        db.add(job_status)
        await db.commit()

        publisher = InProcessJobPublisher()
        await publisher.publish(envelope)
    except Exception as exc:
        logger.error(f"Failed to publish forecast job: {exc}", exc_info=True)


# ============================================================================
# GET /api/forecast/assumptions
# ============================================================================


@router.get("/api/forecast/assumptions")
async def get_assumptions(
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """
    Get all non-deleted manual assumptions for the client.
    Derives included_in_forecast field based on confidence_pct and system_config threshold.
    """
    threshold = await get_forecast_confidence_threshold(db, current_user.client_id)

    stmt = select(ManualAssumption).where(
        and_(
            ManualAssumption.client_id == current_user.client_id,
            ManualAssumption.deleted_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    assumptions_rows = result.scalars().all()

    assumptions_list = []
    for assumption in assumptions_rows:
        entity_name = await get_entity_name(db, assumption.entity_id)
        assumption_date = assumption.date or assumption.expected_date

        assumptions_list.append({
            "id": str(assumption.id),
            "entity_id": str(assumption.entity_id),
            "entity_name": entity_name or "Unknown",
            "currency": assumption.currency,
            "direction": assumption.direction,
            "amount": float(assumption.amount),
            "date": assumption_date.isoformat() if assumption_date else None,
            "category": assumption.category,
            "description": assumption.description,
            "confidence_pct": float(assumption.confidence_pct),
            "included_in_forecast": derive_included_in_forecast(assumption.confidence_pct, threshold),
            "created_by": str(assumption.created_by) if assumption.created_by else None,
            "created_at": assumption.created_at.isoformat() + "Z" if assumption.created_at else None,
            "updated_at": (assumption.updated_at.isoformat() + "Z") if assumption.updated_at else None,
        })

    return {"assumptions": assumptions_list}


# ============================================================================
# POST /api/forecast/assumptions
# ============================================================================


@router.post("/api/forecast/assumptions", status_code=201)
async def create_assumption(
    body: AssumptionCreateBody,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_ASSUMPTIONS)),
) -> dict:
    """
    Create a new manual assumption.
    Validation: direction, amount, date, category, confidence_pct, entity_id.
    Triggers forecast re-run on success (non-blocking).
    """
    # Validation
    if body.direction not in ["Inflow", "Outflow"]:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "direction must be 'Inflow' or 'Outflow'"},
        )

    if body.amount <= 0:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "amount must be > 0"},
        )

    try:
        assumption_date = datetime.fromisoformat(body.date).date()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "date must be ISO format YYYY-MM-DD"},
        )

    if assumption_date < date.today():
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "date must be >= today"},
        )

    if body.category not in ["Payroll", "Tax", "Investment", "Loan Repayment", "Capex", "Operating", "Other"]:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "category must be one of: Payroll, Tax, Investment, Loan Repayment, Capex, Operating, Other"},
        )

    if not (0 <= body.confidence_pct <= 100):
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "confidence_pct must be 0–100"},
        )

    # Validate entity_id exists for this client
    entity_stmt = select(LegalEntity).where(
        and_(
            LegalEntity.id == body.entity_id,
            LegalEntity.client_id == current_user.client_id,
        )
    )
    entity_result = await db.execute(entity_stmt)
    entity = entity_result.scalar()
    if not entity:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "entity_id does not exist for this client"},
        )

    # Create assumption
    assumption = ManualAssumption(
        client_id=current_user.client_id,
        entity_id=body.entity_id,
        description=body.description,
        amount=Decimal(str(body.amount)),
        currency=body.currency,
        date=assumption_date,
        direction=body.direction,
        confidence_pct=Decimal(str(body.confidence_pct)),
        category=body.category,
        created_by=current_user.user_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(assumption)
    await db.commit()
    await db.refresh(assumption)

    # Write audit event
    try:
        await write_audit_event(
            db=db,
            client_id=current_user.client_id,
            user_id=current_user.user_id,
            user_name=current_user.email,
            action="assumption.created",
            entity_type="manual_assumption",
            entity_id=str(assumption.id),
            new_value={
                "direction": body.direction,
                "amount": float(body.amount),
                "date": str(assumption_date),
                "category": body.category,
                "confidence_pct": body.confidence_pct,
            },
        )
    except Exception as exc:
        logger.warning(f"Failed to write audit event for assumption create: {exc}")

    # Publish forecast job (non-blocking)
    await publish_forecast_job(db, current_user.client_id, current_user)

    # Return response with derived field
    threshold = await get_forecast_confidence_threshold(db, current_user.client_id)

    return {
        "id": str(assumption.id),
        "entity_id": str(assumption.entity_id),
        "entity_name": entity.name,
        "currency": assumption.currency,
        "direction": assumption.direction,
        "amount": float(assumption.amount),
        "date": str(assumption_date),
        "category": assumption.category,
        "description": assumption.description,
        "confidence_pct": float(assumption.confidence_pct),
        "included_in_forecast": derive_included_in_forecast(assumption.confidence_pct, threshold),
        "created_by": str(assumption.created_by) if assumption.created_by else None,
        "created_at": assumption.created_at.isoformat() + "Z",
        "updated_at": assumption.updated_at.isoformat() + "Z",
    }


# ============================================================================
# PUT /api/forecast/assumptions/{id}
# ============================================================================


@router.put("/api/forecast/assumptions/{assumption_id}")
async def update_assumption(
    assumption_id: str,
    body: AssumptionUpdateBody,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_ASSUMPTIONS)),
) -> dict:
    """
    Update an assumption.
    Same validation as POST.
    Triggers forecast re-run on success.
    """
    # Validation
    if body.direction not in ["Inflow", "Outflow"]:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "direction must be 'Inflow' or 'Outflow'"},
        )

    if body.amount <= 0:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "amount must be > 0"},
        )

    try:
        assumption_date = datetime.fromisoformat(body.date).date()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "date must be ISO format YYYY-MM-DD"},
        )

    if assumption_date < date.today():
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "date must be >= today"},
        )

    if body.category not in ["Payroll", "Tax", "Investment", "Loan Repayment", "Capex", "Operating", "Other"]:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "category must be one of: Payroll, Tax, Investment, Loan Repayment, Capex, Operating, Other"},
        )

    if not (0 <= body.confidence_pct <= 100):
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "confidence_pct must be 0–100"},
        )

    # Validate entity_id exists for this client
    entity_stmt = select(LegalEntity).where(
        and_(
            LegalEntity.id == body.entity_id,
            LegalEntity.client_id == current_user.client_id,
        )
    )
    entity_result = await db.execute(entity_stmt)
    entity = entity_result.scalar()
    if not entity:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "entity_id does not exist for this client"},
        )

    # Fetch existing assumption
    stmt = select(ManualAssumption).where(
        and_(
            ManualAssumption.id == assumption_id,
            ManualAssumption.client_id == current_user.client_id,
            ManualAssumption.deleted_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    assumption = result.scalar()

    if not assumption:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Assumption not found"},
        )

    # Store old value for audit
    old_value = {
        "direction": assumption.direction,
        "amount": float(assumption.amount),
        "category": assumption.category,
        "confidence_pct": float(assumption.confidence_pct),
    }

    # Update
    assumption.entity_id = body.entity_id
    assumption.description = body.description
    assumption.amount = Decimal(str(body.amount))
    assumption.currency = body.currency
    assumption.date = assumption_date
    assumption.direction = body.direction
    assumption.confidence_pct = Decimal(str(body.confidence_pct))
    assumption.category = body.category
    assumption.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(assumption)

    # Write audit event
    try:
        await write_audit_event(
            db=db,
            client_id=current_user.client_id,
            user_id=current_user.user_id,
            user_name=current_user.email,
            action="assumption.updated",
            entity_type="manual_assumption",
            entity_id=str(assumption.id),
            old_value=old_value,
            new_value={
                "direction": body.direction,
                "amount": float(body.amount),
                "category": body.category,
                "confidence_pct": body.confidence_pct,
            },
        )
    except Exception as exc:
        logger.warning(f"Failed to write audit event for assumption update: {exc}")

    # Publish forecast job (non-blocking)
    await publish_forecast_job(db, current_user.client_id, current_user)

    # Return response with derived field
    threshold = await get_forecast_confidence_threshold(db, current_user.client_id)

    return {
        "id": str(assumption.id),
        "entity_id": str(assumption.entity_id),
        "entity_name": entity.name,
        "currency": assumption.currency,
        "direction": assumption.direction,
        "amount": float(assumption.amount),
        "date": str(assumption_date),
        "category": assumption.category,
        "description": assumption.description,
        "confidence_pct": float(assumption.confidence_pct),
        "included_in_forecast": derive_included_in_forecast(assumption.confidence_pct, threshold),
        "created_by": str(assumption.created_by) if assumption.created_by else None,
        "created_at": assumption.created_at.isoformat() + "Z",
        "updated_at": assumption.updated_at.isoformat() + "Z",
    }


# ============================================================================
# DELETE /api/forecast/assumptions/{id}
# ============================================================================


@router.delete("/api/forecast/assumptions/{assumption_id}")
async def delete_assumption(
    assumption_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_ASSUMPTIONS)),
) -> dict:
    """
    Soft-delete an assumption (set deleted_at).
    Triggers forecast re-run on success.
    """
    stmt = select(ManualAssumption).where(
        and_(
            ManualAssumption.id == assumption_id,
            ManualAssumption.client_id == current_user.client_id,
            ManualAssumption.deleted_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    assumption = result.scalar()

    if not assumption:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Assumption not found"},
        )

    assumption.deleted_at = datetime.utcnow()
    await db.commit()

    # Write audit event
    try:
        await write_audit_event(
            db=db,
            client_id=current_user.client_id,
            user_id=current_user.user_id,
            user_name=current_user.email,
            action="assumption.deleted",
            entity_type="manual_assumption",
            entity_id=str(assumption.id),
            old_value={"deleted_at": None},
            new_value={"deleted_at": assumption.deleted_at.isoformat()},
        )
    except Exception as exc:
        logger.warning(f"Failed to write audit event for assumption delete: {exc}")

    # Publish forecast job (non-blocking)
    await publish_forecast_job(db, current_user.client_id, current_user)

    return {"status": "deleted"}


# ============================================================================
# POST /api/forecast/request
# ============================================================================


@router.post("/api/forecast/request", status_code=202)
async def request_forecast(
    body: ForecastRequestBody,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_ASSUMPTIONS)),
) -> dict:
    """
    Publish a forecast job and return 202.
    Agent 2 calculation is blocked — will return OPENING_BALANCE_UNRESOLVED.
    """
    from app.jobs.in_process import InProcessJobPublisher

    job_id = str(uuid4())
    now = datetime.utcnow()

    envelope = JobEnvelope(
        job_id=job_id,
        job_type=JobType.FORECAST,
        client_id=str(current_user.client_id),
        user_id=str(current_user.user_id),
        requested_at=now,
        payload={
            "triggered_by": "user_request",
            "horizon_days": body.horizon_days or 7,
            "cash_position_date": body.cash_position_date or datetime.utcnow().date().isoformat(),
            "policy_id": body.policy_id or "policy_default",
        },
    )

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

    try:
        publisher = InProcessJobPublisher()
        await publisher.publish(envelope)
    except Exception as exc:
        logger.error(f"Failed to publish forecast job: {exc}")
        raise HTTPException(
            status_code=503,
            detail={"code": "AGENT_ERROR", "message": "Forecast job could not be queued. Please retry."},
        )

    return {
        "forecast_id": job_id,
        "status": JobStatusEnum.QUEUED.value,
        "queued_at": now.isoformat() + "Z",
        "horizon_days": body.horizon_days or 7,
    }


# ============================================================================
# GET /api/forecast/{forecast_id}
# ============================================================================


@router.get("/api/forecast/{forecast_id}")
async def get_forecast_status(
    forecast_id: str,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """
    Poll for forecast result.
    Returns job status while pending/processing.
    Returns OPENING_BALANCE_UNRESOLVED when Agent 2 is blocked.
    """
    stmt = select(JobStatus).where(
        and_(
            JobStatus.job_id == forecast_id,
            JobStatus.client_id == current_user.client_id,
        )
    )
    result = await db.execute(stmt)
    job = result.scalar()

    if not job:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Forecast job not found"},
        )

    # Pending or processing
    if job.status in [JobStatusEnum.QUEUED.value, "processing"]:
        return {
            "forecast_id": str(job.job_id),
            "status": job.status,
            "queued_at": job.requested_at.isoformat() + "Z",
        }

    # Failed
    if job.status == JobStatusEnum.FAILED.value:
        return {
            "forecast_id": str(job.job_id),
            "status": "failed",
            "error": job.error_message or "Forecast job failed. Please retry.",
        }

    # Completed
    if job.status == JobStatusEnum.COMPLETED.value and job.result_id:
        try:
            collection = mongo_db["forecast_results"]
            doc = await collection.find_one({"_id": job.result_id})

            if doc and doc.get("error"):
                # Agent 2 returns OPENING_BALANCE_UNRESOLVED until Session 14 unblocks it
                return {
                    "forecast_id": str(job.job_id),
                    "status": "failed",
                    "error": doc.get("error"),
                }

            return {
                "forecast_id": str(job.job_id),
                "status": "completed",
                "run_id": job.result_id,
                "triggered_by": doc.get("triggered_by", "user_request") if doc else None,
                "as_of": doc.get("as_of", datetime.utcnow().isoformat()) if doc else None,
                "horizons": doc.get("horizons", []) if doc else [],
            }
        except Exception as exc:
            logger.error(f"Failed to retrieve forecast result: {exc}")
            raise HTTPException(
                status_code=500,
                detail={"code": "INTERNAL_ERROR", "message": "Failed to retrieve forecast result"},
            )

    raise HTTPException(
        status_code=500,
        detail={"code": "INTERNAL_ERROR", "message": "Unexpected job status"},
    )


# ============================================================================
# GET /api/forecast/current
# ============================================================================


@router.get("/api/forecast/current")
async def get_current_forecast(
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """
    Returns the latest completed forecast for the client.
    Until Agent 2 is unblocked, returns the blocked error.
    Returns 404 if no forecast has ever been run.
    """
    # Get latest completed forecast job for this client
    stmt = (
        select(JobStatus)
        .where(
            and_(
                JobStatus.client_id == current_user.client_id,
                JobStatus.job_type == JobType.FORECAST.value,
                JobStatus.status == JobStatusEnum.COMPLETED.value,
            )
        )
        .order_by(JobStatus.completed_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    job = result.scalar()

    if not job:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "No forecast has been run yet"},
        )

    try:
        collection = mongo_db["forecast_results"]
        doc = await collection.find_one({"_id": job.result_id})

        if not doc:
            raise HTTPException(
                status_code=500,
                detail={"code": "INTERNAL_ERROR", "message": "Forecast result not found in MongoDB"},
            )

        if doc.get("error"):
            # Agent 2 returns OPENING_BALANCE_UNRESOLVED until Session 14 unblocks it
            return {
                "forecast_id": str(job.job_id),
                "status": "failed",
                "error": doc.get("error"),
            }

        return {
            "forecast_id": str(job.job_id),
            "status": "completed",
            "run_id": job.result_id,
            "triggered_by": doc.get("triggered_by", "user_request"),
            "as_of": doc.get("as_of", datetime.utcnow().isoformat()),
            "horizons": doc.get("horizons", []),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to retrieve current forecast: {exc}")
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to retrieve forecast result"},
        )


# ============================================================================
# GET /api/forecast/variance
# ============================================================================


@router.get("/api/forecast/variance")
async def get_forecast_variance(
    current_user: UserClaims = Depends(get_current_user),
) -> dict:
    """
    Returns 503 — Variance depends on forecast, which is blocked.
    Wire in Session 10 (Agent 5) after forecast unblocked in Session 14.
    """
    raise HTTPException(
        status_code=503,
        detail={"code": "OPENING_BALANCE_UNRESOLVED", "message": "Variance requires forecast calculation. Opening balance anchor rule not yet resolved."},
    )


# ============================================================================
# POST /api/forecast/variance/request
# ============================================================================


@router.post("/api/forecast/variance/request", status_code=503)
async def request_forecast_variance(
    current_user: UserClaims = Depends(require_permission(Permission.EDIT_ASSUMPTIONS)),
) -> dict:
    """
    Returns 503 — Variance depends on forecast, which is blocked.
    Wire in Session 10 (Agent 5) after forecast unblocked in Session 14.
    """
    raise HTTPException(
        status_code=503,
        detail={"code": "OPENING_BALANCE_UNRESOLVED", "message": "Variance requires forecast calculation. Opening balance anchor rule not yet resolved."},
    )
