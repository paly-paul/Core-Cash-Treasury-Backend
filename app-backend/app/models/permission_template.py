from sqlalchemy import Column, ForeignKey, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime

from app.database import Base


class PermissionTemplate(Base):
    __tablename__ = "permission_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    permissions = Column(JSONB, nullable=False, default=[])
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_permission_templates_client_name", "client_id", "name", unique=True),
    )
