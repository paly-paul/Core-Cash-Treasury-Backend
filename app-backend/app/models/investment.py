from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Boolean, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class InvestmentPolicy(Base):
    __tablename__ = "investment_policy"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("legal_entity.id"), nullable=False)
    version = Column(String(50), nullable=False)
    document_path = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="true")
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default="now()", nullable=False)


class InvestmentCutoff(Base):
    __tablename__ = "investment_cutoff"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("legal_entity.id"), nullable=False)
    cutoff_time = Column(Time, nullable=False)
    timezone = Column(String(50), nullable=False)
    investment_account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"), nullable=True)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default="now()", nullable=True)

    __table_args__ = (UniqueConstraint("client_id", "entity_id"),)
