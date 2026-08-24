"""
Pytest configuration for Core Cash tests.
"""
import pytest
import asyncio
import os


def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_db_url():
    """Get test database URL from environment."""
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/core_cash_test")


@pytest.fixture(scope="session")
def test_mongo_url():
    """Get test MongoDB URL from environment."""
    return os.getenv("MONGODB_URI", "mongodb://localhost:27017")
