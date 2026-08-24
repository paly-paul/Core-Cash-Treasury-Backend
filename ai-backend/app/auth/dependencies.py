from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from app.auth.jwt import jwt_validator


security = HTTPBearer()


async def get_current_user(credentials=Depends(security)) -> dict:
    """Extract and validate JWT token from Authorization header."""
    token = credentials.credentials
    try:
        decoded = await jwt_validator.validate_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_id = decoded.get("sub", "")
    email = decoded.get("email", "")
    role = (
        decoded.get("cognito:groups", ["Viewer"])[0]
        if decoded.get("cognito:groups")
        else "Viewer"
    )

    return {
        "user_id": user_id,
        "email": email,
        "role": role,
    }
