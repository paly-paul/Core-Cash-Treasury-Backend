import asyncio
from typing import Callable

from core_cash_shared.schemas.jobs import JobEnvelope

from app.jobs.interface import JobPublisher
from app.jobs.registry import JOB_HANDLERS


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

        # Get handler for this job type
        handler: Callable = JOB_HANDLERS.get(envelope.job_type.value)
        if not handler:
            raise ValueError(f"No handler registered for job type: {envelope.job_type}")

        # Dispatch asynchronously - fire and forget
        asyncio.create_task(handler(envelope))

        return job_id
