"""Agent 4: Action Recommendation

Generates prioritised action recommendations based on Agent 1 (cash position)
and Agent 3 (liquidity risk) outputs. Reads from MongoDB only for agent outputs,
and from PostgreSQL for investment policy.

LLM is mocked in this session (template strings only).
Real Anthropic API wired in Session 12.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.state import AgentState


async def run_agent_4_recommendations(state: AgentState) -> AgentState:
    """Run Action Recommendation Agent."""
    try:
        from app.database import AsyncSessionLocal
        from app.mongo.client import get_mongo_db

        async with AsyncSessionLocal() as db:
            mongo_db = get_mongo_db()
            output = await generate_recommendations_from_outputs(
                db=db, mongo_db=mongo_db, state=state
            )
            state["action_recommendations"] = {
                "raw": output,
                "status": "pending_policy_check"
            }
            return state

    except Exception as e:
        state["errors"]["agent_4"] = str(e)
        return state


async def generate_recommendations_from_outputs(
    db: AsyncSession, mongo_db, state: AgentState
) -> List[Dict[str, Any]]:
    """Generate raw recommendations from Agent 1 and Agent 3 outputs."""

    client_id = state["client_id"]

    # Fetch Agent 1 output from MongoDB
    collection = mongo_db["agent_runs"]
    agent1_doc = await collection.find_one(
        {"client_id": client_id, "agent": "daily_cash_position"},
        sort=[("as_of", -1)],
    )

    if not agent1_doc:
        state["errors"]["agent_4"] = "Missing prerequisite agent output"
        return []

    # Fetch Agent 3 output from MongoDB
    agent3_doc = await collection.find_one(
        {"client_id": client_id, "agent": "liquidity_risk"},
        sort=[("as_of", -1)],
    )

    if not agent3_doc:
        state["errors"]["agent_4"] = "Missing prerequisite agent output"
        return []

    # Fetch investment policy per entity
    investment_policy_by_entity = await get_investment_policy_by_entity(
        db, client_id
    )

    # Fetch system config for significant_outflow_pct
    significant_outflow_pct = await get_system_config_value(
        db, client_id, "significant_outflow_pct", default=10.0
    )

    # Generate recommendations
    recommendations = generate_recommendations(
        agent1_output=agent1_doc,
        agent3_output=agent3_doc,
        investment_policy_by_entity=investment_policy_by_entity,
        significant_outflow_pct=significant_outflow_pct,
    )

    return recommendations


async def get_investment_policy_by_entity(
    db: AsyncSession, client_id: str
) -> Dict[str, bool]:
    """Fetch active investment policies per entity."""
    from app.models.investment import InvestmentPolicy

    stmt = select(InvestmentPolicy).where(
        (InvestmentPolicy.client_id == client_id) &
        (InvestmentPolicy.is_active == True)
    )
    result = await db.execute(stmt)
    policies = result.scalars().all()

    return {policy.entity_id: True for policy in policies}


async def get_system_config_value(
    db: AsyncSession,
    client_id: str,
    key: str,
    default: float = 10.0
) -> float:
    """Fetch system config value, return default if missing."""
    from app.models.system_config import SystemConfig

    stmt = select(SystemConfig).where(
        (SystemConfig.client_id == client_id) &
        (SystemConfig.config_key == key)
    )
    result = await db.execute(stmt)
    config = result.scalar()

    if config and config.config_val:
        try:
            return float(config.config_val)
        except (ValueError, TypeError):
            return default

    return default


def generate_recommendations(
    agent1_output: dict,
    agent3_output: dict,
    investment_policy_by_entity: dict,
    significant_outflow_pct: float = 10.0,
) -> List[dict]:
    """Generate recommendations from Agent 1 and Agent 3 outputs."""
    recommendations = []

    # PRIORITY 1: Active threshold breaches (one recommendation per breach)
    for breach in agent3_output.get("active_breaches", []):
        rec = build_breach_recommendation(breach, agent1_output)
        recommendations.append(rec)

    # PRIORITY 2: Forecast shortfall days
    # TODO: wire from Agent 2 output in Session 14
    # For now: empty, with TODO comment

    # PRIORITY 3: Surplus investment (one per entity with sustained surplus)
    for entity in agent1_output.get("entities", []):
        surplus = detect_surplus(entity, significant_outflow_pct)
        if surplus:
            entity_id = entity["entity_id"]
            has_policy = investment_policy_by_entity.get(entity_id, False)
            rec = build_investment_recommendation(entity, surplus, has_policy)
            recommendations.append(rec)

    # Cap at 10, priority order already set by list ordering above
    return recommendations[:10]


def detect_surplus(entity: dict, significant_outflow_pct: float) -> dict | None:
    """
    Detect if entity has sustained surplus.

    Surplus exists when usable cash for an entity exceeds min_threshold
    by more than significant_outflow_pct % with no material outflow forecast.
    In Session 5a: use simple static rule — surplus if usable_cash_usd
    is > 150% of the sum of min_thresholds for accounts in this entity.
    TODO: replace with forecast-driven surplus detection in Session 14.
    """
    accounts = entity.get("accounts", [])
    total_threshold = sum(
        a.get("min_threshold", 0) for a in accounts
        if a.get("include_in_cash_position")
    )
    usable = entity.get("usable_cash_usd", 0)

    if total_threshold > 0 and usable > total_threshold * 1.5:
        surplus_amount = usable - total_threshold
        return {
            "entity_id": entity["entity_id"],
            "entity_name": entity["entity_name"],
            "usable_cash_usd": usable,
            "surplus_usd": surplus_amount,
            "min_threshold_total": total_threshold,
        }

    return None


def build_breach_recommendation(breach: dict, agent1_output: dict) -> dict:
    """Build a funding recommendation for an active breach.

    LLM MOCK — replace with Anthropic client call in Session 12.
    """
    entity_name = breach["entity_name"]
    account_name = breach["account_name"]
    currency = breach["currency"]
    shortfall = breach["shortfall"]
    min_threshold = breach["min_threshold"]

    return {
        "id": str(uuid4()),
        "priority": 1,
        "type": "Funding",
        "why": (
            f"{entity_name} {currency} balance is {currency} {shortfall:,.0f} "
            f"below the {currency} {min_threshold:,.0f} minimum threshold."
        ),
        "what": (
            f"Evaluate funding of {currency} {shortfall * 1.2:,.0f} to "
            f"{account_name} from available surplus pool, subject to "
            f"Finance Director approval per DOA policy."
        ),
        "when": (
            "Today before treasury close. Delay beyond cut-off means "
            "next business day settlement."
        ),
        "control": {
            "approval_owner": "Finance Director (per DOA policy)",
            "policy_check": "Pass",
            "human_approval_required": True,
        },
        "approval_status": "Pending",
        "approved_by": None,
        "approved_at": None,
    }


def build_investment_recommendation(
    entity: dict,
    surplus: dict,
    has_policy: bool,
) -> dict:
    """Build an investment recommendation for entity surplus.

    LLM MOCK — replace with Anthropic client call in Session 12.
    """
    entity_name = entity["entity_name"]
    surplus_usd = surplus["surplus_usd"]

    if has_policy:
        what = (
            f"Evaluate investment of surplus USD ~{surplus_usd:,.0f} from "
            f"{entity_name} per uploaded investment SOP. Review eligible "
            f"instruments and cut-off times before acting."
        )
        policy_check = "Pass — investment SOP uploaded"
    else:
        # No policy uploaded — downgrade to surplus flag only
        what = (
            f"Surplus of USD ~{surplus_usd:,.0f} identified in {entity_name}. "
            f"No investment SOP uploaded — review company policy before acting. "
            f"Upload investment policy via Config to enable investment recommendations."
        )
        policy_check = "No investment SOP — surplus flagged only"

    return {
        "id": str(uuid4()),
        "priority": 2,
        "type": "Investment",
        "why": (
            f"{entity_name} usable cash has sustained surplus of "
            f"USD {surplus_usd:,.0f} above minimum thresholds."
        ),
        "what": what,
        "when": "Review before end of business day. Check investment cut-off times.",
        "control": {
            "approval_owner": "Treasury Manager (per DOA policy)",
            "policy_check": policy_check,
            "human_approval_required": True,
        },
        "approval_status": "Pending",
        "approved_by": None,
        "approved_at": None,
    }
