from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.pipeline import pipeline
from app.graph.state import AgentState
from core_cash_shared.schemas.jobs import JobEnvelope


async def run_agent_job(
    envelope: JobEnvelope, db: AsyncSession, mongo_db
) -> None:
    """Top-level job orchestrator.

    1. Build initial AgentState from envelope
    2. Run compiled LangGraph pipeline
    3. Write final state to MongoDB agent_runs collection
    On any unhandled exception: log and fail gracefully
    """
    try:
        # Build initial state
        initial_state: AgentState = {
            "job_id": envelope.job_id,
            "client_id": envelope.client_id,
            "user_id": envelope.user_id,
            "requested_at": envelope.requested_at,
            "cash_position": None,
            "liquidity_risk": None,
            "forecast": None,
            "action_recommendations": None,
            "variance_explanation": None,
            "treasury_continuity": None,
            "cfo_summary": None,
            "errors": {},
        }

        # Run pipeline
        final_state = await pipeline.ainvoke(initial_state)

        # Write to MongoDB
        await mongo_db.agent_runs.insert_one(
            {
                "job_id": envelope.job_id,
                "client_id": envelope.client_id,
                "user_id": envelope.user_id,
                "job_type": envelope.job_type.value,
                "requested_at": envelope.requested_at,
                "completed_at": datetime.utcnow(),
                "final_state": dict(final_state),
                "created_at": datetime.utcnow(),
            }
        )
    except Exception as e:
        await mongo_db.agent_runs.insert_one(
            {
                "job_id": envelope.job_id,
                "client_id": envelope.client_id,
                "user_id": envelope.user_id,
                "job_type": envelope.job_type.value,
                "requested_at": envelope.requested_at,
                "error": str(e),
                "created_at": datetime.utcnow(),
            }
        )
