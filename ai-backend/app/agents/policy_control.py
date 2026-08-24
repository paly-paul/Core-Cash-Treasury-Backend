"""Agent 8: Policy Control

Deterministic middleware that validates every recommendation against policy rules.
Runs after Agent 4 in the pipeline. Validates, rewrites forbidden language,
and filters recommendations before they enter the database.

No LLM — fully deterministic.
Core Cash is read-only intelligence. Agents recommend. Humans approve.
Agent 8 enforces this at the pipeline level.
"""
import re
import logging
from typing import Dict, List, Tuple, Any
from datetime import datetime

logger = logging.getLogger(__name__)


# Execution verbs that trigger "human approval only" language rewrite
EXECUTION_VERBS = [
    "Transfer", "Execute", "Send", "Move", "Initiate",
    "Pay", "Wire", "Remit", "Disburse", "Release",
]

# Replacement mapping: evaluative language instead of execution
EVALUATIVE_REPLACEMENTS = {
    "Transfer": "Evaluate transfer of",
    "Execute": "Evaluate",
    "Send": "Consider sending",
    "Move": "Consider moving",
    "Initiate": "Propose initiating",
    "Pay": "Evaluate payment of",
    "Wire": "Evaluate wiring",
    "Remit": "Consider remitting",
    "Disburse": "Evaluate disbursement of",
    "Release": "Consider releasing",
}


class PolicyControlAgent:
    """Deterministic policy control middleware."""

    def run(self, recommendations: List[dict]) -> Tuple[List[dict], List[dict]]:
        """
        Process recommendations through policy controls.
        Returns (approved_recs, blocked_recs).
        """
        return run_policy_control(recommendations)


def validate_and_rewrite(rec: dict) -> Tuple[dict | None, List[str]]:
    """
    Validate one recommendation. Returns (rewritten_rec, []) on pass,
    or (None, [error_reasons]) if the rec must be blocked entirely.

    Rules:
    1. All four fields must be present and non-empty: why, what, when, control
    2. human_approval_required must be True — block if False or missing
    3. Rewrite execution verbs in 'what' field (do not block — rewrite)
    4. approval_status must start as Pending — enforce regardless of input
    """
    errors = []

    # Rule 1: All four fields must be present and non-empty
    for field in ["why", "what", "when", "control"]:
        if not rec.get(field):
            errors.append(f"Missing required field: {field}")

    # Rule 2: human_approval_required must be True — block if False or missing
    control = rec.get("control", {})
    if not control.get("human_approval_required"):
        errors.append("human_approval_required must be True")

    # If hard errors, block entirely
    if errors:
        return None, errors

    # Rule 3: Rewrite execution verbs in 'what' field (do not block — rewrite)
    what = rec["what"]
    for verb, replacement in EVALUATIVE_REPLACEMENTS.items():
        # Word-boundary match: avoid partial replacements
        what = re.sub(rf"\b{verb}\b", replacement, what, flags=re.IGNORECASE)
    rec["what"] = what

    # Rule 4: approval_status must start as Pending — enforce regardless of input
    rec["approval_status"] = "Pending"
    rec["approved_by"] = None
    rec["approved_at"] = None

    return rec, []


def run_policy_control(
    recommendations: List[dict],
) -> Tuple[List[dict], List[dict]]:
    """
    Process all recommendations through policy controls.
    Returns (approved_recs, blocked_recs).

    approved_recs: passed Agent 8 and will be written to MongoDB.
    blocked_recs: logged for observability but NOT written to MongoDB.
    """
    approved = []
    blocked = []

    for rec in recommendations:
        rewritten, errors = validate_and_rewrite(rec)
        if rewritten:
            approved.append(rewritten)
        else:
            blocked_rec = {**rec, "blocked_reasons": errors}
            blocked.append(blocked_rec)
            logger.warning(
                f"Agent 8 blocked recommendation id={rec.get('id')} "
                f"reasons={errors}"
            )

    return approved, blocked


async def write_recommendations_to_mongo(
    mongo_db,
    client_id: str,
    job_id: str,
    approved_recs: List[dict],
    blocked_recs: List[dict],
    agent1_run_id: str,
    agent3_run_id: str,
) -> str:
    """
    Write recommendation run to MongoDB.
    Only approved recommendations are written to the recommendations array.
    Blocked recommendations are logged in blocked_reasons but not in recommendations.

    Returns inserted document _id.
    """
    doc = {
        "job_id": job_id,
        "client_id": client_id,
        "agent": "action_recommendation",
        "created_at": datetime.utcnow(),
        "recommendation_count": len(approved_recs),
        "recommendations": approved_recs,
        "blocked_count": len(blocked_recs),
        "blocked_reasons": [r.get("blocked_reasons") for r in blocked_recs],
        "source_agent_runs": {
            "agent_1": agent1_run_id,
            "agent_3": agent3_run_id,
        },
    }
    result = await mongo_db["recommendations"].insert_one(doc)
    return str(result.inserted_id)
