from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core_cash_shared.schemas.auth import UserClaims
from core_cash_shared.enums import Permission
from app.services.jwt_service import decode_access_token
from app.database import get_db
from jose import JWTError
import structlog

logger = structlog.get_logger()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserClaims:
    """Extract and validate JWT token from HTTP-only cookie or Authorization header."""
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(401, {"code": "UNAUTHORIZED", "message": "Authentication required"})

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(401, {"code": "UNAUTHORIZED", "message": "Invalid or expired token"})

    # Parse permissions from JWT payload
    raw_permissions: list[str] = payload.get("permissions", [])
    permissions: set[Permission] = set()
    for p in raw_permissions:
        try:
            permissions.add(Permission(p))
        except ValueError:
            pass  # Unknown permission string — skip

    return UserClaims(
        sub=payload["sub"],
        email=payload.get("email", ""),
        client_id=payload["client_id"],
        permissions=permissions,
    )


def require_permission(*required: Permission):
    """Gate a route on one or more explicit permissions."""
    async def dependency(user: UserClaims = Depends(get_current_user)) -> UserClaims:
        missing = [p for p in required if not user.has_permission(p)]
        if missing:
            logger.warning("permission_denied", user_id=user.sub,
                           missing=[p.value for p in missing])
            raise HTTPException(403, {"code": "FORBIDDEN",
                                      "message": f"Missing: {[p.value for p in missing]}"})
        return user

    return dependency
