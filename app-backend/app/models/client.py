from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Client(Base):
    __tablename__ = "client"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
