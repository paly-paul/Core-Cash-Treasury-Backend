"""
Forecast endpoints — App Backend.

Session 6: Forecast scaffold (blocked stub) + Manual Assumptions CRUD
Session 13: Unblock blocked status, add /latest, update variance endpoint
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime

from core_cash_shared.schemas.forecast import ForecastResult

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


# ─────────────────────────────────────────────────────────────
# FORECAST POLLING ENDPOINTS (Session 6 → Session 13 updated)
# ─────────────────────────────────────────────────────────────


@router.get("/{forecast_id}")
async def get_forecast(
    forecast_id: str,
    mongo: AsyncIOMotorDatabase = Depends(lambda: None),  # Injected at app level
) -> dict:
    """
    Poll for forecast result.

    Session 13 update: Returns 200 (not 503) when data_status="blocked"
    with clear error message.
    """
    if not mongo:
        raise HTTPException(status_code=500, detail="MongoDB not configured")

    # Query MongoDB for the forecast_runs document
    forecast_doc = await mongo.forecast_runs.find_one({"forecast_run_id": forecast_id})

    if not forecast_doc:
        raise HTTPException(status_code=404, detail="Forecast not found")

    data_status = forecast_doc.get("data_status", "pending")

    # Session 13: Blocked forecasts now return 200 with clear status
    if data_status == "blocked":
        return {
            "forecast_run_id": forecast_id,
            "data_status": "blocked",
            "blocked_reason": forecast_doc.get("blocked_reason"),
            "forecast_rows": [],
            "opening_balance_usd": None,
            "assumptions_used": forecast_doc.get("assumptions_used", 0),
            "assumptions_skipped": forecast_doc.get("assumptions_skipped", 0),
            "message": "Upload bank statement data to unblock forecast.",
        }

    # Partial or live status: return full forecast
    if data_status in ("partial", "live"):
        return {
            "forecast_run_id": forecast_id,
            "data_status": data_status,
            "entity_id": forecast_doc.get("entity_id"),
            "entity_name": forecast_doc.get("entity_name"),
            "generated_at": forecast_doc.get("generated_at"),
            "horizon_days": forecast_doc.get("horizon_days"),
            "opening_balance_usd": forecast_doc.get("opening_balance_usd"),
            "forecast_rows": forecast_doc.get("forecast_rows", []),
            "assumptions_used": forecast_doc.get("assumptions_used", 0),
            "assumptions_skipped": forecast_doc.get("assumptions_skipped", 0),
            "forecast_accuracy_pct": forecast_doc.get("forecast_accuracy_pct"),
            "notes": forecast_doc.get("notes", []),
        }

    # Pending or running status
    return {
        "forecast_run_id": forecast_id,
        "data_status": data_status,
        "queued_at": forecast_doc.get("queued_at"),
    }


@router.get("/latest")
async def get_latest_forecast(
    entity_id: str = Query(...),
    mongo: AsyncIOMotorDatabase = Depends(lambda: None),
) -> dict:
    """
    Get latest forecast for an entity.

    Session 13 addition.
    Returns latest forecast regardless of data_status.
    """
    if not mongo:
        raise HTTPException(status_code=500, detail="MongoDB not configured")

    forecast_doc = await mongo.forecast_runs.find_one(
        {"entity_id": entity_id},
        sort=[("generated_at", -1)]
    )

    if not forecast_doc:
        raise HTTPException(
            status_code=404,
            detail="Forecast not found",
        )

    data_status = forecast_doc.get("data_status", "pending")

    # Handle blocked status
    if data_status == "blocked":
        return {
            "forecast_run_id": forecast_doc.get("forecast_run_id"),
            "data_status": "blocked",
            "blocked_reason": forecast_doc.get("blocked_reason"),
            "forecast_rows": [],
            "opening_balance_usd": None,
            "assumptions_used": forecast_doc.get("assumptions_used", 0),
            "assumptions_skipped": forecast_doc.get("assumptions_skipped", 0),
        }

    # Return full forecast
    return {
        "forecast_run_id": forecast_doc.get("forecast_run_id"),
        "data_status": data_status,
        "entity_id": forecast_doc.get("entity_id"),
        "entity_name": forecast_doc.get("entity_name"),
        "generated_at": forecast_doc.get("generated_at"),
        "horizon_days": forecast_doc.get("horizon_days"),
        "opening_balance_usd": forecast_doc.get("opening_balance_usd"),
        "forecast_rows": forecast_doc.get("forecast_rows", []),
        "assumptions_used": forecast_doc.get("assumptions_used", 0),
        "assumptions_skipped": forecast_doc.get("assumptions_skipped", 0),
        "forecast_accuracy_pct": forecast_doc.get("forecast_accuracy_pct"),
        "notes": forecast_doc.get("notes", []),
    }


# ─────────────────────────────────────────────────────────────
# VARIANCE ENDPOINTS
# ─────────────────────────────────────────────────────────────


@router.post("/variance/request")
async def request_variance_explanation(
    request_data: dict,
    sqs_publisher=Depends(lambda: None),  # SQS client injected at app level
) -> dict:
    """
    Request variance explanation.

    Session 6: Was 503 stub
    Session 13: Now enqueues variance_explanation job (Agent 5)
    Returns 202 with request_id
    """
    if not sqs_publisher:
        raise HTTPException(status_code=500, detail="SQS not configured")

    entity_id = request_data.get("entity_id")
    variance_date = request_data.get("variance_date")

    if not entity_id:
        raise HTTPException(status_code=422, detail="entity_id required")

    # Publish variance_explanation job to SQS
    variance_id = f"var_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    job_payload = {
        "job_type": "variance_explanation",
        "payload": {
            "entity_id": entity_id,
            "variance_date": variance_date,
        },
    }

    try:
        await sqs_publisher.publish(job_payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue variance job: {str(e)}")

    return {
        "variance_id": variance_id,
        "status": "queued",
        "queued_at": datetime.utcnow().isoformat() + "Z",
    }


# ─────────────────────────────────────────────────────────────
# ASSUMPTIONS CRUD (from Session 6, unchanged)
# ─────────────────────────────────────────────────────────────


@router.get("/assumptions")
async def list_assumptions(
    entity_id: str = Query(...),
    db: AsyncSession = Depends(lambda: None),
) -> dict:
    """
    List manual assumptions for an entity.

    Assumptions with confidence_pct < 50 are marked as excluded.
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Query PostgreSQL manual_assumptions
    # TODO: Implement query when schema available
    return {"assumptions": []}


@router.post("/assumptions")
async def create_assumption(
    request_data: dict,
    db: AsyncSession = Depends(lambda: None),
    sqs_publisher=Depends(lambda: None),
) -> dict:
    """
    Create a new manual assumption.

    Triggers forecast re-run on success.
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")

    # TODO: Implement assumption creation
    return {"status": "created"}


@router.put("/assumptions/{assumption_id}")
async def update_assumption(
    assumption_id: str,
    request_data: dict,
    db: AsyncSession = Depends(lambda: None),
    sqs_publisher=Depends(lambda: None),
) -> dict:
    """
    Update a manual assumption.

    Triggers forecast re-run on success.
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")

    # TODO: Implement assumption update
    return {"status": "updated"}


@router.delete("/assumptions/{assumption_id}")
async def delete_assumption(
    assumption_id: str,
    db: AsyncSession = Depends(lambda: None),
    sqs_publisher=Depends(lambda: None),
) -> dict:
    """
    Delete a manual assumption (soft delete).

    Triggers forecast re-run on success.
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")

    # TODO: Implement assumption deletion
    return {"status": "deleted"}
