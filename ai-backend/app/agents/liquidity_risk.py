"""Agent 3: Liquidity Risk

Deterministic agent that computes liquidity risk score based on active breaches,
stale feeds, and AR concentration. Reads from PostgreSQL and MongoDB, writes to MongoDB.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.state import AgentState


async def run_agent_3_liquidity_risk(state: AgentState) -> AgentState:
    """Run Liquidity Risk Agent."""
    try:
        from app.database import AsyncSessionLocal
        from app.mongo.client import get_mongo_db

        async with AsyncSessionLocal() as db:
            mongo_db = get_mongo_db()
            output = await compute_liquidity_risk(
                db=db, mongo_db=mongo_db, state=state
            )
            state["liquidity_risk"] = output
            return state

    except Exception as e:
        state["errors"]["agent_3"] = str(e)
        return state


async def compute_liquidity_risk(
    db: AsyncSession, mongo_db, state: AgentState
) -> Dict[str, Any]:
    """Compute liquidity risk score from Agent 1 output and AR data."""

    client_id = state["client_id"]
    run_id = str(uuid4())
    as_of = datetime.utcnow()

    # Get Agent 1 output from MongoDB
    collection = mongo_db["agent_runs"]
    agent_1_doc = await collection.find_one(
        {"client_id": client_id, "agent": "daily_cash_position"},
        sort=[("as_of", -1)],
    )

    if not agent_1_doc:
        return {
            "run_id": run_id,
            "client_id": client_id,
            "agent": "liquidity_risk",
            "as_of": as_of.isoformat() + "Z",
            "error": {
                "code": "AGENT_ERROR",
                "message": "Daily cash position must be computed before liquidity risk can be assessed.",
            },
        }

    # Extract Agent 1 outputs
    active_breaches = agent_1_doc.get("active_breaches", [])
    stale_feeds = agent_1_doc.get("stale_feeds", [])

    # Add confidence field to stale_feeds if missing (from Agent 1 output)
    for feed in stale_feeds:
        if "confidence" not in feed:
            feed["confidence"] = "Low"

    # Compute AR concentration risk
    ar_rows = await get_ar_data(db, client_id)
    ar_concentration = compute_ar_concentration(ar_rows)

    # Compute risk score
    score_result = compute_risk_score(
        active_breaches=active_breaches,
        stale_feeds=stale_feeds,
        ar_concentration_pct=ar_concentration["top_3_share_pct"],
        forecast_shortfall_days=[],
    )

    # Generate narrative
    narrative = generate_narrative(
        risk_level=score_result["risk_level"],
        active_breaches=active_breaches,
        ar_concentration=ar_concentration,
        stale_feeds=stale_feeds,
    )

    # Build output
    output = {
        "run_id": run_id,
        "client_id": client_id,
        "agent": "liquidity_risk",
        "as_of": as_of.isoformat() + "Z",
        "risk_score": score_result["risk_score"],
        "risk_level": score_result["risk_level"],
        "score_breakdown": score_result["score_breakdown"],
        "active_breaches": active_breaches,
        "forecast_shortfall_days": [],
        "ar_concentration_risk": ar_concentration,
        "stale_feeds": stale_feeds,
        "narrative": narrative,
    }

    # Write to MongoDB
    result = await collection.insert_one(output)
    output["_id"] = str(result.inserted_id)

    return output


async def get_ar_data(db: AsyncSession, client_id: str) -> List[Dict[str, Any]]:
    """Fetch AR data for given client."""
    from app.models.ar_data import ARData

    stmt = select(ARData).where(
        (ARData.client_id == client_id) & (ARData.status.in_(["Open", "Overdue"]))
    )
    result = await db.execute(stmt)
    ar_records = result.scalars().all()

    return [
        {
            "counterparty_name": ar.counterparty_name,
            "amount_local": float(ar.amount_local or 0),
            "amount_usd": float(ar.amount_usd or 0),
            "currency": ar.currency,
        }
        for ar in ar_records
    ]


def compute_risk_score(
    active_breaches: List[Dict],
    stale_feeds: List[Dict],
    ar_concentration_pct: float,
    forecast_shortfall_days: List[str],
) -> Dict[str, Any]:
    """Compute risk score from components."""
    base = 1

    # +2 per active breach, capped at 6
    breach_pts = min(len(active_breaches) * 2, 6)

    # +1 if ANY feed is > 48 hours stale
    stale_pts = 1 if any(f.get("hours_stale", 0) > 48 for f in stale_feeds) else 0

    # +1 if top 3 AR counterparties exceed 70% of total
    ar_conc_pts = 1 if ar_concentration_pct > 70.0 else 0

    # TODO: wire shortfall_pts from Agent 2 forecast output in Session 14
    shortfall_pts = 0

    raw = base + breach_pts + stale_pts + ar_conc_pts + shortfall_pts
    score = min(raw, 10)

    risk_level = (
        "Low" if score <= 3 else "Medium" if score <= 6 else "High"
    )

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "score_breakdown": {
            "base": base,
            "breach_points": breach_pts,
            "stale_feed_points": stale_pts,
            "ar_concentration_points": ar_conc_pts,
            "shortfall_points": shortfall_pts,
            "raw_total": raw,
            "capped": raw > 10,
        },
    }


def compute_ar_concentration(ar_rows: List[Dict]) -> Dict[str, Any]:
    """Compute AR concentration risk."""
    if not ar_rows:
        return {
            "top_3_share_pct": 0.0,
            "threshold_pct": 70.0,
            "breached": False,
            "high_single_counterparty": False,
            "top_counterparties": [],
        }

    # Group by counterparty, sum amount_usd
    by_counterparty: Dict[str, float] = {}
    total_ar_usd = 0.0
    for row in ar_rows:
        amt = float(row.get("amount_usd") or row.get("amount_local", 0))
        by_counterparty[row["counterparty_name"]] = (
            by_counterparty.get(row["counterparty_name"], 0.0) + amt
        )
        total_ar_usd += amt

    if total_ar_usd == 0:
        return {
            "top_3_share_pct": 0.0,
            "threshold_pct": 70.0,
            "breached": False,
            "high_single_counterparty": False,
            "top_counterparties": [],
        }

    sorted_parties = sorted(by_counterparty.items(), key=lambda x: x[1], reverse=True)
    top_3 = sorted_parties[:3]
    top_3_total = sum(amt for _, amt in top_3)
    top_3_share_pct = round(top_3_total / total_ar_usd * 100, 1)

    # high_single_counterparty: any single > 40%
    top_1_share = (
        (sorted_parties[0][1] / total_ar_usd * 100) if sorted_parties else 0
    )
    high_single = top_1_share > 40.0

    top_counterparties = [
        {"name": name, "share_pct": round(amt / total_ar_usd * 100, 1)}
        for name, amt in top_3
    ]

    return {
        "top_3_share_pct": top_3_share_pct,
        "threshold_pct": 70.0,
        "breached": top_3_share_pct > 70.0,
        "high_single_counterparty": high_single,
        "top_counterparties": top_counterparties,
    }


def generate_narrative(
    risk_level: str,
    active_breaches: List[Dict],
    ar_concentration: Dict,
    stale_feeds: List[Dict],
) -> str:
    """Generate deterministic narrative from risk components."""
    breach_part = (
        f"{len(active_breaches)} active breach(es) of minimum threshold."
        if active_breaches
        else "No active threshold breaches."
    )
    conc_pct = ar_concentration["top_3_share_pct"]
    conc_part = (
        f"AR concentration at {conc_pct:.1f}% — above 70% threshold."
        if ar_concentration["breached"]
        else f"AR concentration at {conc_pct:.1f}% — within 70% threshold."
    )
    stale_part = (
        f"{len(stale_feeds)} stale feed(s) detected (>48h)."
        if stale_feeds
        else "All bank feeds current."
    )
    return f"Liquidity risk is {risk_level}. {breach_part} {conc_part} {stale_part}"
