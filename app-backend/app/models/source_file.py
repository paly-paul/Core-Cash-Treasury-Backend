from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class SourceFile(Base):
    __tablename__ = "source_file"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    file_type = Column(String(50), nullable=False)
    file_format = Column(String(20))
    filename = Column(String(500))
    rows_imported = Column(Integer)
    status = Column(String(20), nullable=False, default="pending")
    error_message = Column(Text)
