from sqlalchemy import Column, ForeignKey, String, Boolean, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from app.database import Base


class Users(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    mfa_secret = Column(String(255))
    last_login_at = Column(DateTime)
    password_changed_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_users_client_email", "client_id", "email", unique=True),
        Index("idx_users_active", "client_id", "is_active"),
    )
