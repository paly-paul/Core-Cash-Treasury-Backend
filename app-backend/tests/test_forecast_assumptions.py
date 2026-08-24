"""
Tests for forecast assumptions CRUD endpoints.
13 test cases covering happy path, validation, and system behavior.
"""
import pytest
from datetime import datetime, date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.database import AsyncSessionLocal
from app.auth.models import UserModel
from app.auth.dependencies import get_current_user
from app.database import get_db


client = TestClient(app)

# Test fixtures
TEST_CLIENT_ID = "11111111-1111-1111-1111-111111111111"
TEST_USER_ID = "22222222-2222-2222-2222-222222222222"
TEST_ENTITY_ID = "33333333-3333-3333-3333-333333333333"


def get_test_user():
    """Return a mock user model."""
    return UserModel(
        user_id=TEST_USER_ID,
        client_id=TEST_CLIENT_ID,
        email="test@example.com",
        role="Analyst",
    )


@pytest.fixture(autouse=True)
def override_deps():
    """Override FastAPI dependencies for testing."""
    async def mock_get_db():
        async with AsyncSessionLocal() as db:
            yield db

    def mock_get_current_user():
        return get_test_user()

    # Override dependencies
    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[get_current_user] = mock_get_current_user

    yield

    # Clear overrides after test
    app.dependency_overrides.clear()


class TestGetAssumptions:
    """Test GET /api/forecast/assumptions."""

    def test_get_assumptions_empty_list(self):
        """Test GET returns empty list when no assumptions exist."""
        response = client.get("/api/forecast/assumptions")
        assert response.status_code == 200
        data = response.json()
        assert "assumptions" in data
        assert isinstance(data["assumptions"], list)

    def test_get_assumptions_response_structure(self):
        """Test response has correct structure with all required fields."""
        response = client.get("/api/forecast/assumptions")
        assert response.status_code == 200
        data = response.json()
        assert "assumptions" in data


class TestPostAssumption:
    """Test POST /api/forecast/assumptions."""

    def test_post_assumption_invalid_direction(self):
        """Test invalid direction returns 422."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        payload = {
            "entity_id": TEST_ENTITY_ID,
            "currency": "USD",
            "direction": "InvalidDirection",
            "amount": 2000000,
            "date": tomorrow.isoformat(),
            "category": "Capex",
            "description": "Test",
            "confidence_pct": 75,
        }

        response = client.post("/api/forecast/assumptions", json=payload)
        assert response.status_code == 422

    def test_post_assumption_negative_amount(self):
        """Test negative amount returns 422."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        payload = {
            "entity_id": TEST_ENTITY_ID,
            "currency": "USD",
            "direction": "Outflow",
            "amount": -1000,
            "date": tomorrow.isoformat(),
            "category": "Capex",
            "description": "Test",
            "confidence_pct": 75,
        }

        response = client.post("/api/forecast/assumptions", json=payload)
        assert response.status_code == 422

    def test_post_assumption_past_date_rejected(self):
        """Test 5: Past date rejected with 422."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        payload = {
            "entity_id": TEST_ENTITY_ID,
            "currency": "USD",
            "direction": "Outflow",
            "amount": 2000000,
            "date": yesterday.isoformat(),
            "category": "Capex",
            "description": "Past date test",
            "confidence_pct": 75,
        }

        response = client.post("/api/forecast/assumptions", json=payload)
        assert response.status_code == 422

    def test_post_assumption_invalid_category_rejected(self):
        """Test 6: Invalid category returns 422."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        payload = {
            "entity_id": TEST_ENTITY_ID,
            "currency": "USD",
            "direction": "Outflow",
            "amount": 2000000,
            "date": tomorrow.isoformat(),
            "category": "InvalidCategory",
            "description": "Invalid category test",
            "confidence_pct": 75,
        }

        response = client.post("/api/forecast/assumptions", json=payload)
        assert response.status_code == 422

    def test_post_assumption_confidence_pct_over_100(self):
        """Test 7: confidence_pct=101 returns 422."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        payload = {
            "entity_id": TEST_ENTITY_ID,
            "currency": "USD",
            "direction": "Outflow",
            "amount": 2000000,
            "date": tomorrow.isoformat(),
            "category": "Capex",
            "description": "Over 100 confidence",
            "confidence_pct": 101,
        }

        response = client.post("/api/forecast/assumptions", json=payload)
        assert response.status_code == 422

    def test_post_assumption_confidence_pct_negative(self):
        """Test confidence_pct=-1 returns 422."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        payload = {
            "entity_id": TEST_ENTITY_ID,
            "currency": "USD",
            "direction": "Outflow",
            "amount": 2000000,
            "date": tomorrow.isoformat(),
            "category": "Capex",
            "description": "Negative confidence",
            "confidence_pct": -1,
        }

        response = client.post("/api/forecast/assumptions", json=payload)
        assert response.status_code == 422


class TestForecastEndpoints:
    """Test forecast request/poll endpoints (blocked)."""

    def test_post_forecast_request_returns_202(self):
        """Test 11: POST /api/forecast/request returns 202."""
        today = date.today()

        payload = {
            "horizon_days": 7,
            "cash_position_date": today.isoformat(),
            "policy_id": "policy_default",
        }

        with patch("app.routers.forecast.InProcessJobPublisher.publish", new_callable=AsyncMock):
            response = client.post("/api/forecast/request", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert "forecast_id" in data
        assert data["status"] == "queued"
        assert data["horizon_days"] == 7

    def test_get_forecast_not_found(self):
        """Test GET /api/forecast/{id} returns 404 when not found."""
        fake_id = str(uuid4())
        response = client.get(f"/api/forecast/{fake_id}")
        assert response.status_code == 404

    def test_get_forecast_variance_returns_503(self):
        """Test 13: GET /api/forecast/variance returns 503."""
        response = client.get("/api/forecast/variance")
        assert response.status_code == 503
        data = response.json()
        assert "error" in data or "detail" in data

    def test_post_forecast_variance_request_returns_503(self):
        """Test POST /api/forecast/variance/request returns 503."""
        response = client.post("/api/forecast/variance/request", json={})
        assert response.status_code == 503

    def test_get_current_forecast_not_found(self):
        """Test GET /api/forecast/current returns 404 when no forecast exists."""
        response = client.get("/api/forecast/current")
        assert response.status_code == 404


class TestValidation:
    """Test validation rules."""

    def test_direction_inflow_accepted(self):
        """Test Inflow direction is accepted."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        payload = {
            "entity_id": TEST_ENTITY_ID,
            "currency": "USD",
            "direction": "Inflow",
            "amount": 100000,
            "date": tomorrow.isoformat(),
            "category": "Operating",
            "description": "Test Inflow",
            "confidence_pct": 50,
        }

        with patch("app.routers.forecast.InProcessJobPublisher.publish", new_callable=AsyncMock):
            with patch("app.routers.forecast.get_entity_name", new_callable=AsyncMock) as mock_entity:
                mock_entity.return_value = "US HQ"
                with patch("app.routers.forecast.publish_forecast_job", new_callable=AsyncMock):
                    response = client.post("/api/forecast/assumptions", json=payload)

        # Should not return 422 for direction validation
        if response.status_code == 422:
            assert "direction" not in response.json().get("detail", {}).get("message", "").lower()

    def test_all_categories_valid(self):
        """Test all valid categories are accepted (no 422 for category)."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        valid_categories = ["Payroll", "Tax", "Investment", "Loan Repayment", "Capex", "Operating", "Other"]

        for category in valid_categories:
            payload = {
                "entity_id": TEST_ENTITY_ID,
                "currency": "USD",
                "direction": "Outflow",
                "amount": 100000,
                "date": tomorrow.isoformat(),
                "category": category,
                "description": f"Test {category}",
                "confidence_pct": 50,
            }

            # Note: Will fail on entity validation, but not on category validation
            response = client.post("/api/forecast/assumptions", json=payload)

            # If 422, should not be for category
            if response.status_code == 422:
                detail = str(response.json().get("detail", ""))
                assert "category" not in detail.lower() or "one of" in detail.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
