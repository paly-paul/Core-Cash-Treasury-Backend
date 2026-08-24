from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Numeric, Date
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class ManualAssumption(Base):
    __tablename__ = "manual_assumptions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("legal_entity.id"), nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    expected_date = Column(Date, nullable=True)
    date = Column(Date, nullable=True)
    direction = Column(String(10), nullable=False)
    confidence_pct = Column(Numeric(5, 2), nullable=False)
    category = Column(String(50), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default="now()", nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default="now()", nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
