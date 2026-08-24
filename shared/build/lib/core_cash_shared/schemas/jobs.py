import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..enums import JobStatus, JobType


class JobEnvelope(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_type: JobType
    client_id: str
    user_id: str
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    payload: Dict[str, Any] = Field(default_factory=dict)


class JobStatusResponse(BaseModel):
    request_id: str
    status: JobStatus
    job_type: JobType
    requested_at: datetime
    completed_at: Optional[datetime] = None
    result_id: Optional[str] = None
    error: Optional[str] = None
