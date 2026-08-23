from typing import Optional

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    severity: str
    field: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
