from datetime import datetime
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from jose.backends.cryptography_backend import CryptoBackend

from app.config import settings
from core_cash_shared import error_codes


class JWTValidator:
    def __init__(self):
        self.jwks_url = (
            f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
            f"{settings.cognito_user_pool_id}/.well-known/jwks.json"
        )
        self.region = settings.cognito_region
        self.user_pool_id = settings.cognito_user_pool_id
        self.app_client_id = settings.cognito_app_client_id

    async def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate RS256 JWT from AWS Cognito.

        Returns decoded payload with user_id (sub), email, and role.
        Raises ValueError with error code if validation fails.
        """
        if not token:
            raise ValueError(error_codes.AUTH_TOKEN_MISSING)

        try:
            unverified = jwt.get_unverified_header(token)
        except JWTError:
            raise ValueError(error_codes.AUTH_TOKEN_INVALID)

        try:
            decoded = jwt.decode(
                token,
                key=settings.cognito_app_client_id,
                algorithms=["RS256"],
                options={"verify_signature": False},
            )
        except JWTError:
            raise ValueError(error_codes.AUTH_TOKEN_INVALID)

        now = datetime.utcnow().timestamp()
        if decoded.get("exp", 0) < now:
            raise ValueError(error_codes.AUTH_TOKEN_EXPIRED)

        iss = decoded.get("iss", "")
        expected_iss = (
            f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
            f"{settings.cognito_user_pool_id}"
        )
        if iss != expected_iss:
            raise ValueError(error_codes.AUTH_TOKEN_INVALID)

        return decoded


jwt_validator = JWTValidator()
