from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    entity_id: Optional[str] = None
    session_id: Optional[str] = None


class ChatSSEEvent(BaseModel):
    event: Literal["token", "done", "error", "context"]
    data: str
