from pydantic import BaseModel
from uuid import UUID


class UserModel(BaseModel):
    user_id: str
    client_id: UUID
    email: str
    role: str
