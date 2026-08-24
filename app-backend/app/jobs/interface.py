from abc import ABC, abstractmethod

from core_cash_shared.schemas.jobs import JobEnvelope


class JobPublisher(ABC):
    @abstractmethod
    async def publish(self, envelope: JobEnvelope) -> str:
        """Publish a job. Returns job_id."""
        ...
