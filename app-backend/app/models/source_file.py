from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID

from app.database import Base


class SourceFile(Base):
    __tablename__ = "source_file"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)
    upload_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="Processing")
    rows_received = Column(Integer, default=0)
    rows_valid = Column(Integer, default=0)
    rows_failed = Column(Integer, default=0)
    error_detail = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default="now()", nullable=False)
    parsed_at = Column(DateTime(timezone=True))
