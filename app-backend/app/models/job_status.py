from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class JobStatus(Base):
    __tablename__ = "job_status"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    job_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    job_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    requested_at = Column(DateTime(timezone=True), server_default="now()", nullable=False)
    completed_at = Column(DateTime(timezone=True))
    result_id = Column(Text)
    error_message = Column(Text)
