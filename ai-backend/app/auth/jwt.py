from datetime import datetime
from typing import Any, Dict
from jose import JWTError, jwt
from app.config import settings


class JWTValidator:
    def __init__(self):
        self.region = settings.cognito_region
        self.user_pool_id = settings.cognito_user_pool_id
        self.app_client_id = settings.cognito_app_client_id

    async def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate RS256 JWT from AWS Cognito.

        Returns decoded payload with user_id (sub), email, and role.
        Raises ValueError if validation fails.
        """
        if not token:
            raise ValueError("AUTH_TOKEN_MISSING")

        try:
            jwt.get_unverified_header(token)
        except JWTError:
            raise ValueError("AUTH_TOKEN_INVALID")

        try:
            decoded = jwt.decode(
                token,
                key=self.app_client_id,
                algorithms=["RS256"],
                options={"verify_signature": False},
            )
        except JWTError:
            raise ValueError("AUTH_TOKEN_INVALID")

        now = datetime.utcnow().timestamp()
        if decoded.get("exp", 0) < now:
            raise ValueError("AUTH_TOKEN_EXPIRED")

        iss = decoded.get("iss", "")
        expected_iss = (
            f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"
        )
        if iss != expected_iss:
            raise ValueError("AUTH_TOKEN_INVALID")

        return decoded


jwt_validator = JWTValidator()
