import asyncio
from datetime import datetime

from sqlalchemy import select, update

from core_cash_shared import JobStatus as JobStatusEnum, JobType
from core_cash_shared.schemas.jobs import JobEnvelope

from app.jobs.interface import JobPublisher
from app.database import AsyncSessionLocal
from app.models.job_status import JobStatus
from app.mongo.client import get_mongo_db


class InProcessJobPublisher(JobPublisher):
    """In-process job publisher using asyncio task dispatching.

    When SQS replaces this, create SQSJobPublisher(JobPublisher)
    and swap it in config — no agent code changes required.
    """

    async def publish(self, envelope: JobEnvelope) -> str:
        """Publish a job and dispatch to handler via asyncio.

        Returns job_id.
        """
        job_id = envelope.job_id

        # Dispatch asynchronously - fire and forget
        asyncio.create_task(self._execute_job(envelope))

        return job_id

    async def _execute_job(self, envelope: JobEnvelope) -> None:
        """Execute job based on type."""
        async with AsyncSessionLocal() as db:
            try:
                # Update job_status to processing
                stmt = (
                    update(JobStatus)
                    .where(JobStatus.job_id == envelope.job_id)
                    .values(status=JobStatusEnum.PROCESSING.value)
                )
                await db.execute(stmt)
                await db.commit()

                mongo_db = get_mongo_db()

                # Route by job type — MVP: in-process dispatch to AI Backend
                if envelope.job_type == JobType.CASH_POSITION:
                    # Dynamic import to avoid circular dependency
                    # In production with SQS: replace this with queue handler
                    try:
                        from ai_backend.app.worker.runner import run_agent_job
                    except ImportError:
                        # Fallback: try adding ai-backend to path
                        import sys
                        import os
                        ai_path = os.path.abspath(
                            os.path.join(os.path.dirname(__file__), "../../../ai-backend")
                        )
                        if ai_path not in sys.path:
                            sys.path.insert(0, ai_path)
                        from app.worker.runner import run_agent_job

                    await run_agent_job(envelope=envelope, db=db, mongo_db=mongo_db)

                    # Get result_id from MongoDB
                    collection = mongo_db["agent_runs"]
                    doc = await collection.find_one(
                        {"job_id": envelope.job_id, "cash_position": {"$exists": True}}
                    )
                    result_id = str(doc["_id"]) if doc else None
                else:
                    raise ValueError(f"Unknown job type: {envelope.job_type}")

                # Update job_status to completed
                stmt = (
                    update(JobStatus)
                    .where(JobStatus.job_id == envelope.job_id)
                    .values(
                        status=JobStatusEnum.COMPLETED.value,
                        completed_at=datetime.utcnow(),
                        result_id=result_id,
                    )
                )
                await db.execute(stmt)
                await db.commit()

            except Exception as e:
                # Update job_status to failed
                stmt = (
                    update(JobStatus)
                    .where(JobStatus.job_id == envelope.job_id)
                    .values(
                        status=JobStatusEnum.FAILED.value,
                        completed_at=datetime.utcnow(),
                        error_message=str(e),
                    )
                )
                await db.execute(stmt)
                await db.commit()
