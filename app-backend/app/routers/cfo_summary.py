"""CFO Summary and Daily Briefing endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime
from typing import Dict, Any, Optional
from uuid import uuid4

from app.security import get_current_user, require_role
from app.database import get_db
from app.models.user import User
from app.job_publisher import InProcessJobPublisher
from app.mongo.client import get_mongo_db

router = APIRouter(prefix="/api/cfo-summary", tags=["cfo-summary"])
briefing_router = APIRouter(prefix="/api/daily-briefing", tags=["daily-briefing"])


@router.post("/request")
async def request_cfo_summary(
    current_user: User = Depends(require_role(["Analyst", "TreasuryManager", "CFO"])),
    db=Depends(get_db),
) -> Dict[str, Any]:
    """
    POST /api/cfo-summary/request
    Publishes job_type="cfo_summary" job
    Response 202: { summary_id, status: "queued", queued_at }
    """
    try:
        summary_id = f"cfo_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{str(uuid4())[:8]}"

        publisher = InProcessJobPublisher()
        await publisher.publish(
            job_id=summary_id,
            job_type="cfo_summary",
            client_id=str(current_user.client_id),
            payload={},
        )

        return {
            "summary_id": summary_id,
            "status": "queued",
            "queued_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to publish CFO Summary job: {str(e)}",
        )


@router.get("/{summary_id}")
async def get_cfo_summary(
    summary_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    GET /api/cfo-summary/{summary_id}
    Polls job_status, then reads MongoDB cfo_reports when completed
    """
    mongo = get_mongo_db()

    # Query job_status for this summary
    job_status_row = mongo["job_status"].find_one({
        "job_id": summary_id,
        "client_id": str(current_user.client_id),
    })

    if not job_status_row:
        raise HTTPException(status_code=404, detail="Summary not found")

    status_val = job_status_row.get("status")

    # If still processing, return status only
    if status_val in ["queued", "processing"]:
        return {
            "summary_id": summary_id,
            "status": status_val,
            "queued_at": job_status_row.get("created_at", {}).isoformat() + "Z" if job_status_row.get("created_at") else None,
        }

    # If failed, return error
    if status_val == "failed":
        return {
            "summary_id": summary_id,
            "status": "failed",
            "error": job_status_row.get("error_message", "Unknown error"),
        }

    # If completed, read from MongoDB cfo_reports
    if status_val == "completed":
        result_doc = mongo["cfo_reports"].find_one({
            "client_id": str(current_user.client_id),
            "summary_id": summary_id,
        })
        if result_doc:
            result_doc.pop("_id", None)
            return result_doc

    raise HTTPException(status_code=404, detail="Summary result not found")


@router.get("/latest")
async def get_latest_cfo_summary(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    GET /api/cfo-summary/latest
    Synchronous — reads most recent completed document from MongoDB cfo_reports
    Returns full CFO Summary shape; 404 if none exists
    """
    mongo = get_mongo_db()

    doc = mongo["cfo_reports"].find_one(
        {"client_id": str(current_user.client_id)},
        sort=[("created_at", -1)],
    )

    if not doc:
        raise HTTPException(status_code=404, detail="No CFO Summary found")

    doc.pop("_id", None)
    return doc


@router.get("/live-insights")
async def get_live_insights(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    GET /api/cfo-summary/live-insights
    Synchronous read from latest Agent 1 + Agent 3 MongoDB outputs
    Does NOT trigger a new agent run
    """
    mongo = get_mongo_db()

    # Get latest cash position from Agent 1
    cash_doc = mongo["cash_position"].find_one(
        {"client_id": str(current_user.client_id)},
        sort=[("created_at", -1)],
    )

    # Get latest liquidity risk from Agent 3
    risk_doc = mongo["liquidity_risk"].find_one(
        {"client_id": str(current_user.client_id)},
        sort=[("created_at", -1)],
    )

    usable_cash = float(cash_doc.get("usable_cash_usd", 0)) if cash_doc else 0
    risk_score = risk_doc.get("risk_score", 0) if risk_doc else 0
    as_of = cash_doc.get("as_of") if cash_doc else datetime.utcnow()

    # Compute cash runway (simplified until Agent 2 unblocked)
    daily_outflows = []
    if cash_doc:
        daily_outflows = cash_doc.get("daily_actuals", [])[-30:]

    significant_threshold = usable_cash * 0.10 if usable_cash > 0 else 0
    clean_outflows = [
        d.get("outflow_usd", 0) for d in daily_outflows
        if d.get("outflow_usd", 0) <= significant_threshold
    ]

    avg_daily_outflow = (sum(clean_outflows) / len(clean_outflows)) if clean_outflows else 0.1
    cash_runway_days = int(usable_cash / avg_daily_outflow) if avg_daily_outflow > 0 else 999

    cash_runway_note = None
    for d in daily_outflows:
        if d.get("outflow_usd", 0) > significant_threshold:
            cash_runway_note = f"Excludes {d.get('date', 'unknown')} one-off outflow of USD {d.get('outflow_usd', 0):,.0f}"
            break

    return {
        "as_of": as_of.isoformat() + "Z" if hasattr(as_of, 'isoformat') else str(as_of),
        "cash_runway_days": cash_runway_days,
        "cash_runway_note": cash_runway_note,
        "liquidity_risk_score": risk_score,
        "variance_pct": None,  # null until Agent 5 wired
        "forecast_accuracy_pct": None,  # null until Agent 2 unblocked
        "trend_7d": [],  # empty until Agent 2 unblocked
    }


@router.get("/export")
async def export_cfo_summary(
    current_user: User = Depends(get_current_user),
):
    """
    GET /api/cfo-summary/export
    Stub: return 501 Not Implemented
    # TODO: implement PDF export in a future session
    """
    raise HTTPException(
        status_code=501,
        detail="CFO Summary export not yet available",
    )


@briefing_router.post("/request")
async def request_daily_briefing(
    current_user: User = Depends(require_role(["Analyst", "TreasuryManager", "CFO"])),
) -> Dict[str, Any]:
    """
    POST /api/daily-briefing/request
    Publishes job_type="cfo_summary" with payload={"mode": "briefing"}
    Response 202: { run_id, status: "queued", queued_at }
    """
    try:
        run_id = f"dbrf_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{str(uuid4())[:8]}"

        publisher = InProcessJobPublisher()
        await publisher.publish(
            job_id=run_id,
            job_type="cfo_summary",
            client_id=str(current_user.client_id),
            payload={"mode": "briefing"},
        )

        return {
            "run_id": run_id,
            "status": "queued",
            "queued_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to publish Daily Briefing job: {str(e)}",
        )


@briefing_router.get("/latest")
async def get_latest_daily_briefing(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    GET /api/daily-briefing/latest
    Synchronous — reads most recent document from MongoDB daily_briefings collection
    Returns briefing shape with behind_us, ahead_of_us, if_nothing_changes
    404 if none exists
    """
    mongo = get_mongo_db()

    doc = mongo["daily_briefings"].find_one(
        {"client_id": str(current_user.client_id)},
        sort=[("generated_at", -1)],
    )

    if not doc:
        raise HTTPException(status_code=404, detail="No Daily Briefing found")

    doc.pop("_id", None)
    return doc
