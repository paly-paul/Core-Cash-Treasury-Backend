from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    user_name = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Text, nullable=True)
    old_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=True)
    ip_address = Column(INET, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default="now()", nullable=False)

    __table_args__ = (
        Index("idx_audit_log_client_created", client_id, "created_at"),
        Index("idx_audit_log_user", user_id),
        Index("idx_audit_log_entity", entity_type, entity_id),
    )
