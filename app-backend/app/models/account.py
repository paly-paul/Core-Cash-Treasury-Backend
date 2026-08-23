from sqlalchemy import Boolean, Column, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Account(Base):
    __tablename__ = "account"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("legal_entity.id"), nullable=False)
    bank_id = Column(UUID(as_uuid=True), ForeignKey("bank.id"))
    account_name = Column(String(255), nullable=False)
    bank_account_number = Column(String(50))
    currency = Column(String(3), nullable=False)
    min_threshold = Column(Numeric(15, 2), nullable=False, default=0)
    restricted_flag = Column(Boolean, nullable=False, default=False)
    od_limit = Column(Numeric(15, 2))
    od_utilised_amount = Column(Numeric(15, 2))
    refresh_frequency = Column(String(20), nullable=False, default="Daily")
    include_in_cash_position = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
