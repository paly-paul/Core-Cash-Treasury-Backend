"""
Negative tests for polling & async jobs.
Tests: non-existent job IDs, missing required fields, invalid request parameters.
"""
import pytest
import httpx
from tests.jwt_helper import make_analyst_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        yield client


class TestAsyncNegative:
    """Test async job and polling validation."""

    @pytest.mark.asyncio
    async def test_g1_poll_nonexistent_recommendation_job(self, http_client):
        """G1: Poll non-existent recommendation job returns 404."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/recommendations/rec_99999999_000000_xxxxxxxx",
            headers=headers
        )

        assert response.status_code == 404
        assert response.json().get("error", {}).get("code") == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_g2_poll_nonexistent_forecast_job(self, http_client):
        """G2: Poll non-existent forecast job returns 404."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/forecast/fct_99999999_000000_xxxxxxxx",
            headers=headers
        )

        assert response.status_code == 404
        assert response.json().get("error", {}).get("code") == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_g3_poll_nonexistent_variance_job(self, http_client):
        """G3: Poll non-existent variance job returns 404."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/forecast/variance/var_99999999_000000_xxxxxxxx",
            headers=headers
        )

        assert response.status_code == 404
        assert response.json().get("error", {}).get("code") == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_g4_recommendation_request_missing_cash_position_date(self, http_client):
        """G4: Recommendation request missing cash_position_date returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/recommendations/request",
            json={
                "entity_id": "entity-test-001"
                # Missing cash_position_date
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "cash_position_date" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_g5_forecast_request_horizon_zero_rejected(self, http_client):
        """G5: Forecast request with horizon_days = 0 returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/request",
            json={
                "entity_id": "entity-test-001",
                "horizon_days": 0
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "horizon" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_g6_forecast_request_horizon_exceeds_max(self, http_client):
        """G6: Forecast request with horizon_days > 60 returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/request",
            json={
                "entity_id": "entity-test-001",
                "horizon_days": 90
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "horizon" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_g7_variance_request_cross_client_access_denied(self, http_client):
        """G7: Variance request with forecast_id from different client returns 403/404."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Assume there's a forecast from a different client
        # Try to request variance for it
        response = await http_client.post(
            "/api/forecast/variance/request",
            json={
                "forecast_id": "fct_different_client_xxxxxxxx"
            },
            headers=headers
        )

        # Must NOT succeed with cross-client access
        assert response.status_code in [403, 404]
