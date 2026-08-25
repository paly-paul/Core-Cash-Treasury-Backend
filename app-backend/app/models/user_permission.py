from sqlalchemy import Column, ForeignKey, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from app.database import Base


class UserPermission(Base):
    __tablename__ = "user_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission = Column(String(100), nullable=False)
    grant_type = Column(String(10), nullable=False)  # 'grant' or 'revoke'
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

    __table_args__ = (
        Index("idx_user_permissions_lookup", "client_id", "user_id"),
        Index("idx_user_permissions_unique", "client_id", "user_id", "permission", unique=True),
    )
