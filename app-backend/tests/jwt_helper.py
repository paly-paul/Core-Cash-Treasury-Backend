"""
JWT helper for integration tests.
Creates signed JWTs for testing role-based endpoints.
"""
import os
from datetime import datetime, timedelta
from typing import Optional
import jwt


JWT_SECRET = os.getenv("TEST_JWT_SECRET", "test-secret-key-for-signing-jwts-in-tests")
JWT_ALGORITHM = "HS256"


def make_token(
    role: str = "TreasuryManager",
    client_id: str = "client-test-001",
    user_id: str = "user-test-001",
    email: str = "treasurer@testcorp.com",
) -> str:
    """Create a signed JWT token."""
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "email": email,
        "client_id": client_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def make_viewer_token() -> str:
    """Create a Viewer role JWT."""
    return make_token(role="Viewer")


def make_cfo_token() -> str:
    """Create a CFO role JWT."""
    return make_token(role="CFO")


def make_analyst_token() -> str:
    """Create an Analyst role JWT."""
    return make_token(role="Analyst")


def make_treasury_manager_token() -> str:
    """Create a TreasuryManager role JWT."""
    return make_token(role="TreasuryManager")
