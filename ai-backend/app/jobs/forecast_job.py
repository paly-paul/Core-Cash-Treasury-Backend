"""
Forecast job handler for AI Backend.

Publishes forecast jobs from App Backend via SQS.
AI Backend consumes, runs ForecastAgent, writes to MongoDB.
"""

from core_cash_shared.schemas.jobs import JobEnvelope
from app.agents.forecast import ForecastAgent, AgentState


async def run_forecast_job(
    job_envelope: JobEnvelope,
    db,  # AsyncSession
    mongo,  # AsyncIOMotorDatabase
) -> None:
    """
    Execute a forecast job.

    Args:
        job_envelope: SQS job message
        db: PostgreSQL async session
        mongo: MongoDB async client
    """
    entity_id = job_envelope.payload.get("entity_id")

    agent = ForecastAgent(db=db, mongo=mongo)

    state = AgentState(
        client_id=job_envelope.client_id,
        entity_id=entity_id,
        job_id=job_envelope.job_id,
        errors={},
    )

    await agent.run(state)
