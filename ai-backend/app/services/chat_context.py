from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from sqlalchemy.ext.asyncio import AsyncSession


async def load_chat_context(
    client_id: str,
    entity_id: Optional[str],
    mongo_db: AsyncIOMotorDatabase,
    pg_db: AsyncSession,
) -> dict:
    """
    Loads a compact context snapshot to inject into the system prompt.
    All reads are SELECT-only. Never returns None — returns empty defaults.
    """

    context = {
        "cash_position": None,
        "risk_level": None,
        "risk_score": None,
        "active_breaches": [],
        "pending_recommendations": [],
        "entity_name": None,
    }

    query = {"client_id": client_id}
    if entity_id:
        query["entity_id"] = entity_id

    try:
        cash_doc = await mongo_db.cash_positions.find_one(
            query, sort=[("computed_at", -1)]
        )
        if cash_doc:
            context["cash_position"] = cash_doc.get("total_usable_cash_usd")
            context["entity_name"] = cash_doc.get("entity_name")
    except Exception:
        pass

    try:
        risk_doc = await mongo_db.liquidity_risk.find_one(
            query, sort=[("computed_at", -1)]
        )
        if risk_doc:
            context["risk_level"] = risk_doc.get("risk_level")
            context["risk_score"] = risk_doc.get("risk_score")
            context["active_breaches"] = risk_doc.get("active_breaches", [])[:3]
    except Exception:
        pass

    try:
        rec_query = {**query, "approval_status": "Pending"}
        cursor = mongo_db.recommendations.find(
            rec_query, sort=[("created_at", -1)], limit=5
        )
        recs = await cursor.to_list(length=5)
        context["pending_recommendations"] = [
            {"id": str(r.get("_id")), "what": r.get("what", ""), "priority": r.get("priority")}
            for r in recs
        ]
    except Exception:
        pass

    return context
