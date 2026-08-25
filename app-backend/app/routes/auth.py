from fastapi import APIRouter, Response, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr
from app.database import get_db
from app.services.auth_service import AuthService
from app.auth.dependencies import get_current_user
from core_cash_shared.schemas.auth import UserClaims
import structlog

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = structlog.get_logger()

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
COOKIE_SECURE = False  # False for local dev; True for production
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    client_id: str


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return JWT tokens."""
    ip = request.client.host if request.client else "unknown"
    device_hint = request.headers.get("User-Agent", "")[:255]
    service = AuthService(db)
    result = await service.login(body.client_id, body.email.lower(), body.password, ip, device_hint)

    if result is None:
        # Uniform error — never reveal which field was wrong
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Invalid credentials"})

    # Set HTTP-only cookies
    response.set_cookie(
        ACCESS_COOKIE, result["access_token"],
        httponly=COOKIE_HTTPONLY, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, max_age=3600
    )
    response.set_cookie(
        REFRESH_COOKIE, result["refresh_token"],
        httponly=COOKIE_HTTPONLY, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, max_age=86400 * 30,
        path="/auth/refresh"
    )

    return {"user": result["user"]}


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Logout user and revoke refresh token."""
    raw_refresh = request.cookies.get(REFRESH_COOKIE)
    if raw_refresh:
        await AuthService(db).logout(raw_refresh)

    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE, path="/auth/refresh")


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token."""
    raw_refresh = request.cookies.get(REFRESH_COOKIE)
    if not raw_refresh:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "No refresh token"})

    ip = request.client.host if request.client else "unknown"
    result = await AuthService(db).refresh(raw_refresh, ip)

    if result is None:
        response.delete_cookie(REFRESH_COOKIE, path="/auth/refresh")
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Refresh token invalid or expired"})

    response.set_cookie(
        ACCESS_COOKIE, result["access_token"],
        httponly=COOKIE_HTTPONLY, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, max_age=3600
    )
    response.set_cookie(
        REFRESH_COOKIE, result["refresh_token"],
        httponly=COOKIE_HTTPONLY, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, max_age=86400 * 30,
        path="/auth/refresh"
    )

    return {"message": "Token refreshed"}


@router.get("/me")
async def me(user: UserClaims = Depends(get_current_user)):
    """Get current user info."""
    return {
        "id": user.sub,
        "email": user.email,
        "client_id": user.client_id,
        "permissions": [p.value for p in user.permissions],
    }
