from datetime import datetime
from typing import Any, Dict
from jose import JWTError, jwt
from app.config import settings


class JWTValidator:
    def __init__(self):
        self.public_key = settings.jwt_public_key
        self.algorithm = settings.jwt_algorithm

    async def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate RS256 JWT using the custom public key.

        Returns decoded payload with user_id (sub), email, and permissions.
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
                key=self.public_key,
                algorithms=[self.algorithm],
            )
        except JWTError:
            raise ValueError("AUTH_TOKEN_INVALID")

        if decoded.get("type") != "access":
            raise ValueError("AUTH_TOKEN_INVALID")

        return decoded


jwt_validator = JWTValidator()
