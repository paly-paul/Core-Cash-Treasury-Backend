from sqlalchemy import Column, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Transaction(Base):
    __tablename__ = "transaction"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"), nullable=False)
    statement_id = Column(UUID(as_uuid=True), ForeignKey("statement.id"))
    transaction_date = Column(Date, nullable=False)
    value_date = Column(Date)
    amount = Column(Numeric(15, 2), nullable=False)
    direction = Column(String(10), nullable=False)
    description = Column(Text)
    reference = Column(String(255))
