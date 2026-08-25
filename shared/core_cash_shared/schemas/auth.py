from pydantic import BaseModel, Field
from typing import Optional
from core_cash_shared.enums import Permission


class UserClaims(BaseModel):
    """JWT claims representing the authenticated user."""
    sub: str  # user UUID
    email: str
    client_id: str
    permissions: set[Permission] = Field(default_factory=set)

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions

    def has_any(self, *permissions: Permission) -> bool:
        return any(p in self.permissions for p in permissions)

    def has_all(self, *permissions: Permission) -> bool:
        return all(p in self.permissions for p in permissions)
