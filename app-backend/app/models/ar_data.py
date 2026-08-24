from sqlalchemy import Column, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class ARData(Base):
    __tablename__ = "ar_data"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    source_file_id = Column(UUID(as_uuid=True), ForeignKey("source_file.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("legal_entity.id"))
    counterparty_name = Column(String(255), nullable=False)
    invoice_number = Column(String(100))
    invoice_date = Column(Date)
    due_date = Column(Date)
    currency = Column(String(3), nullable=False)
    amount_local = Column(Numeric(18, 2), nullable=False)
    amount_usd = Column(Numeric(18, 2))
    status = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default="now()", nullable=False)
