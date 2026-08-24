from pydantic import BaseModel


class UserModel(BaseModel):
    user_id: str
    email: str
    role: str
