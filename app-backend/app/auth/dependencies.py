from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

from app.auth.jwt import jwt_validator
from app.auth.models import UserModel
from core_cash_shared import error_codes

security = HTTPBearer()


async def get_current_user(credentials=Depends(security)) -> UserModel:
    """Extract and validate JWT token from Authorization header."""
    token = credentials.credentials
    try:
        decoded = await jwt_validator.validate_token(token)
    except ValueError as e:
        error_code = str(e)
        if error_code == error_codes.AUTH_TOKEN_EXPIRED:
            raise HTTPException(status_code=401, detail=error_code)
        elif error_code == error_codes.AUTH_TOKEN_MISSING:
            raise HTTPException(status_code=401, detail=error_code)
        else:
            raise HTTPException(status_code=401, detail=error_codes.AUTH_TOKEN_INVALID)

    user_id = decoded.get("sub", "")
    email = decoded.get("email", "")
    role = decoded.get("cognito:groups", ["Viewer"])[0] if decoded.get("cognito:groups") else "Viewer"

    return UserModel(user_id=user_id, email=email, role=role)


def require_role(allowed_roles: list[str]):
    """Factory for role-based access control."""

    async def check_role(user: UserModel = Depends(get_current_user)) -> UserModel:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail=error_codes.AUTH_PERMISSION_DENIED)
        return user

    return check_role
