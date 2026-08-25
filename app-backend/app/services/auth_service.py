from datetime import datetime, timedelta
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.users import Users
from app.models.refresh_token import RefreshToken
from app.services.jwt_service import (
    create_access_token, create_refresh_token, hash_token
)
from app.services.permission_service import load_user_permissions
from app.config import settings
import structlog

logger = structlog.get_logger()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Login ---
    async def login(
        self, client_id: str, email: str, password: str, ip: str, device_hint: str
    ) -> dict | None:
        """
        Authenticate user. Returns token pair or None if credentials invalid.
        Never reveal whether email or password was wrong — always return the same error.
        """
        user = await self._get_user_by_email(client_id, email)
        if not user or not user.is_active:
            # Still run bcrypt to prevent timing attacks
            pwd_context.verify("dummy", "$2b$12$dummy_hash_to_prevent_timing_attack_placeholder_value")
            return None
        if not pwd_context.verify(password, user.password_hash):
            logger.warning("failed_login", user_id=str(user.id), ip=ip)
            return None

        # Load permissions from DB
        permissions = await load_user_permissions(self.db, str(user.client_id), str(user.id))
        permission_strings = [p.value for p in permissions]

        # Issue tokens
        access_token = create_access_token(
            user_id=str(user.id),
            client_id=str(user.client_id),
            email=user.email,
            permissions=permission_strings,
        )
        raw_refresh, refresh_hash = create_refresh_token()

        # Store refresh token
        rt = RefreshToken(
            user_id=user.id,
            client_id=user.client_id,
            token_hash=refresh_hash,
            device_hint=device_hint[:255] if device_hint else None,
            ip_address=ip[:50] if ip else None,
            expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days),
        )
        self.db.add(rt)

        # Update last_login_at
        user.last_login_at = datetime.utcnow()
        await self.db.commit()

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "is_admin": user.is_admin,
            }
        }

    # --- Logout ---
    async def logout(self, raw_refresh_token: str) -> None:
        """Revoke the refresh token. Access token expires naturally (max 60 min)."""
        token_hash = hash_token(raw_refresh_token)
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at == None
            )
        )
        rt = result.scalar_one_or_none()
        if rt:
            rt.revoked_at = datetime.utcnow()
            await self.db.commit()

    # --- Refresh ---
    async def refresh(self, raw_refresh_token: str, ip: str) -> dict | None:
        """
        Exchange a valid refresh token for a new access token + rotated refresh token.
        Old refresh token is revoked. Implements refresh token rotation.
        """
        token_hash = hash_token(raw_refresh_token)
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at == None,
                RefreshToken.expires_at > datetime.utcnow()
            )
        )
        rt = result.scalar_one_or_none()
        if not rt:
            return None

        # Load user
        user_result = await self.db.execute(
            select(Users).where(Users.id == rt.user_id, Users.is_active == True)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return None

        # Load current permissions (re-read from DB on refresh — picks up any admin changes)
        permissions = await load_user_permissions(self.db, str(user.client_id), str(user.id))
        permission_strings = [p.value for p in permissions]

        # Revoke old refresh token
        rt.revoked_at = datetime.utcnow()

        # Issue new tokens
        access_token = create_access_token(
            user_id=str(user.id),
            client_id=str(user.client_id),
            email=user.email,
            permissions=permission_strings,
        )
        raw_new, new_hash = create_refresh_token()
        new_rt = RefreshToken(
            user_id=user.id,
            client_id=user.client_id,
            token_hash=new_hash,
            device_hint=rt.device_hint,
            ip_address=ip[:50] if ip else None,
            expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days),
        )
        self.db.add(new_rt)
        await self.db.commit()

        return {
            "access_token": access_token,
            "refresh_token": raw_new,
            "token_type": "bearer",
        }

    # --- Helpers ---
    async def _get_user_by_email(self, client_id: str, email: str) -> Users | None:
        result = await self.db.execute(
            select(Users).where(
                Users.client_id == client_id,
                Users.email == email.lower()
            )
        )
        return result.scalar_one_or_none()
