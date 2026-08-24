from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Bank(Base):
    __tablename__ = "bank"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    name = Column(String(255), nullable=False)
    swift_code = Column(String(11))
