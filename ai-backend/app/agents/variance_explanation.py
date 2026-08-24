"""Agent 5: Variance Explanation

Deterministic agent that explains why actual cash differed from forecast.
Computes variance arithmetic, identifies drivers, and reports unexplained variance.
LLM is mocked with template strings; will be wired in Session 12.
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.graph.state import AgentState
from core_cash_shared.schemas.variance import VarianceDriver


async def run_agent_5_variance(state: AgentState) -> AgentState:
    """Run Variance Explanation Agent."""
    try:
        from app.database import AsyncSessionLocal
        from app.mongo.client import get_mongo_db

        async with AsyncSessionLocal() as db:
            mongo_db = get_mongo_db()
            output = await compute_variance_explanation(
                db=db, mongo_db=mongo_db, state=state
            )
            state["variance_explanation"] = output
            return state

    except Exception as e:
        state["errors"]["agent_5"] = str(e)
        return state


async def compute_variance_explanation(
    db, mongo_db, state: AgentState
) -> Dict[str, Any]:
    """Compute variance explanation from mock or real forecast data."""

    client_id = state["client_id"]
    variance_id = str(uuid4())
    computed_at = datetime.utcnow()

    # Get entity_id from payload if available (for job-based calls)
    entity_id = state.get("entity_id")
    if not entity_id:
        # Fallback: use first entity from Agent 1
        cash_pos = state.get("cash_position", {})
        if cash_pos and "entities" in cash_pos and len(cash_pos["entities"]) > 0:
            entity_id = cash_pos["entities"][0]["entity_id"]

    if not entity_id:
        return {
            "variance_id": variance_id,
            "data_status": "unavailable",
            "error_code": "VARIANCE_DATA_UNAVAILABLE",
            "message": "No entity found to compute variance for.",
            "computed_at": computed_at.isoformat() + "Z",
        }

    # Try to get entity name from database
    entity_name = entity_id
    try:
        from sqlalchemy import select
        from app.models.entity import Entity

        result = await db.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if entity:
            entity_name = entity.name
    except Exception:
        pass

    # Check if forecast data is available (STEP 1)
    collection = mongo_db["forecast_runs"]
    forecast_doc = await collection.find_one(
        {"client_id": client_id, "entity_id": entity_id},
        sort=[("computed_at", -1)],
    )

    if not forecast_doc:
        return {
            "variance_id": variance_id,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "data_status": "unavailable",
            "error_code": "VARIANCE_DATA_UNAVAILABLE",
            "message": "Forecast data not available. Agent 2 (Forecast) must run first.",
            "computed_at": computed_at.isoformat() + "Z",
            "client_id": client_id,
        }

    # Use mock data for now (STEP 2)
    actual_closing_usd = 4_250_000.00
    forecast_closing_usd = 4_100_000.00
    data_status = "mock"

    analysis_date = (date.today() - timedelta(days=1)).isoformat()

    # Compute variance arithmetic (STEP 3)
    total_variance_usd = actual_closing_usd - forecast_closing_usd

    if forecast_closing_usd == 0:
        variance_pct = 0.0
    else:
        variance_pct = (total_variance_usd / abs(forecast_closing_usd)) * 100

    within_tolerance = abs(variance_pct) <= 5.0
    forecast_accuracy_pct = max(0.0, 100.0 - abs(variance_pct))

    # Build mock drivers (STEP 4)
    drivers = [
        VarianceDriver(
            category="Collections",
            actual_usd=1_800_000,
            forecast_usd=1_600_000,
            variance_usd=200_000,
            one_off_flag=False,
        ),
        VarianceDriver(
            category="Payroll",
            actual_usd=950_000,
            forecast_usd=900_000,
            variance_usd=50_000,
            one_off_flag=False,
        ),
        VarianceDriver(
            category="Capital Equipment",
            actual_usd=750_000,
            forecast_usd=500_000,
            variance_usd=250_000,
            one_off_flag=True,
            one_off_basis="Single equipment purchase exceeding 3× average daily outflow of $250,000",
        ),
    ]

    # Compute unexplained variance (STEP 4 continued)
    drivers_sum = sum(d.variance_usd for d in drivers)
    unexplained_variance_usd = total_variance_usd - drivers_sum

    unexplained_variance_note = None
    if abs(unexplained_variance_usd) > 0:
        unexplained_variance_note = (
            f"Residual variance of {unexplained_variance_usd:,.0f} USD "
            f"not attributed to identified drivers. May reflect timing differences, "
            f"unmatched transactions, or rounding in forecast model."
        )

    # Generate narrative (STEP 5 - mocked)
    direction = "above" if total_variance_usd > 0 else "below"
    tolerance_status = "within tolerance" if within_tolerance else "outside tolerance"
    one_offs = [d for d in drivers if d.one_off_flag]
    one_off_note = ""
    if one_offs:
        cats = ", ".join(d.category for d in one_offs)
        one_off_note = f" One-off items identified in: {cats}."

    narrative = (
        f"Actual closing balance was {abs(variance_pct):.1f}% {direction} forecast, "
        f"{tolerance_status} (±5% threshold).{one_off_note} "
        f"Forecast accuracy: {forecast_accuracy_pct:.1f}%. "
        f"Unexplained residual: {unexplained_variance_usd:,.0f} USD."
    )

    # Write to MongoDB (STEP 6)
    variance_collection = mongo_db["variance_explanations"]
    variance_doc = {
        "variance_id": variance_id,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "analysis_date": analysis_date,
        "actual_closing_usd": actual_closing_usd,
        "forecast_closing_usd": forecast_closing_usd,
        "total_variance_usd": total_variance_usd,
        "variance_pct": variance_pct,
        "within_tolerance": within_tolerance,
        "forecast_accuracy_pct": forecast_accuracy_pct,
        "drivers": [d.model_dump() for d in drivers],
        "unexplained_variance_usd": unexplained_variance_usd,
        "unexplained_variance_note": unexplained_variance_note,
        "narrative": narrative,
        "data_status": data_status,
        "computed_at": computed_at.isoformat() + "Z",
        "client_id": client_id,
    }
    await variance_collection.insert_one(variance_doc)

    return {
        "variance_id": variance_id,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "analysis_date": analysis_date,
        "actual_closing_usd": actual_closing_usd,
        "forecast_closing_usd": forecast_closing_usd,
        "total_variance_usd": total_variance_usd,
        "variance_pct": variance_pct,
        "within_tolerance": within_tolerance,
        "forecast_accuracy_pct": forecast_accuracy_pct,
        "drivers": [d.model_dump() for d in drivers],
        "unexplained_variance_usd": unexplained_variance_usd,
        "unexplained_variance_note": unexplained_variance_note,
        "narrative": narrative,
        "data_status": data_status,
        "computed_at": computed_at.isoformat() + "Z",
        "status": "completed",
    }
