from sqlalchemy import Column, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class FXRate(Base):
    __tablename__ = "fx_rates"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    currency_from = Column(String(3), nullable=False)
    currency_to = Column(String(3), nullable=False, server_default="USD")
    rate = Column(Numeric(18, 6), nullable=False)
    rate_date = Column(Date, nullable=False)
    entered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    entered_at = Column(DateTime(timezone=True), server_default="now()", nullable=False)

    __table_args__ = (UniqueConstraint("client_id", "currency_from", "rate_date"),)
