from sqlalchemy import Column, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Statement(Base):
    __tablename__ = "statement"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"), nullable=False)
    statement_date = Column(Date, nullable=False)
    closing_balance = Column(Numeric(15, 2), nullable=False)
    available_balance = Column(Numeric(15, 2))
    currency = Column(String(3), nullable=False)
    source = Column(String(50))

    __table_args__ = (UniqueConstraint("account_id", "statement_date"),)
