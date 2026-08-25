from sqlalchemy import Column, ForeignKey, String, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from app.database import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_password_reset_tokens_user", "user_id"),
        Index("idx_password_reset_tokens_hash", "token_hash"),
    )
