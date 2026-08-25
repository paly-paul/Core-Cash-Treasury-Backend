from fastapi import Depends, HTTPException, Request
from app.auth.jwt import jwt_validator
from core_cash_shared.enums import Permission


async def get_current_user(request: Request) -> dict:
    """Extract and validate JWT token from Authorization header or cookies."""
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        decoded = await jwt_validator.validate_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # Parse permissions from JWT payload
    raw_permissions: list[str] = decoded.get("permissions", [])
    permissions: set[Permission] = set()
    for p in raw_permissions:
        try:
            permissions.add(Permission(p))
        except ValueError:
            pass  # Unknown permission string — skip

    return {
        "user_id": decoded.get("sub", ""),
        "email": decoded.get("email", ""),
        "client_id": decoded.get("client_id", ""),
        "permissions": permissions,
    }
