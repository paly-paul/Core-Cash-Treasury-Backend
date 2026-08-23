from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Users(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_id = Column(UUID(as_uuid=True), ForeignKey("client.id"), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    cognito_sub = Column(String(255), unique=True)
    role = Column(String(50), nullable=False, default="Viewer")
