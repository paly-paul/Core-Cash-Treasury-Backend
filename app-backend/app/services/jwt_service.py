import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from app.config import settings
import structlog

logger = structlog.get_logger()

ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days


def create_access_token(
    user_id: str,
    client_id: str,
    email: str,
    permissions: list[str],
) -> str:
    """
    Create a short-lived RS256 JWT.
    Permissions are embedded in the token so routes can gate
    without a DB lookup on every request.
    """
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "client_id": client_id,
        "email": email,
        "permissions": permissions,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_private_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """
    Validate and decode an access token.
    Raises JWTError on invalid/expired.
    """
    payload = jwt.decode(
        token,
        settings.jwt_public_key,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != "access":
        raise JWTError("Not an access token")
    return payload


def create_refresh_token() -> tuple[str, str]:
    """
    Generate a cryptographically random refresh token.
    Returns (raw_token, token_hash).
    Store only the hash in DB; send the raw token to client.
    """
    raw = secrets.token_urlsafe(64)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()
