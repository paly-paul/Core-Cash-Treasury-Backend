"""
Integration tests for liquidity risk flow.
"""
import pytest
import httpx
import asyncio
from tests.jwt_helper import make_treasury_manager_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        yield client


@pytest.mark.asyncio
class TestLiquidityRiskFlow:
    """Test liquidity risk assessment."""

    async def test_liquidity_risk_after_cash_position(self, http_client):
        """
        POST /api/liquidity-risk/request → 202
        Poll until Completed
        Assert risk_score in [1,10], risk_level in ["Low", "Medium", "High"]
        Assert ar_concentration_risk present, concentration_risk NOT present
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Request liquidity risk assessment
        response = await http_client.post(
            "/api/liquidity-risk/request",
            json={"entity_id": "entity-test-001"},
            headers=headers,
        )

        assert response.status_code == 202, f"Expected 202, got {response.status_code}"
        data = response.json()
        assert "request_id" in data
        request_id = data["request_id"]

        # Poll until completed
        max_retries = 30
        for i in range(max_retries):
            response = await http_client.get(
                f"/api/liquidity-risk/{request_id}",
                headers=headers,
            )
            assert response.status_code == 200
            data = response.json()

            if data.get("status") == "Completed":
                break
            elif data.get("status") == "Failed":
                pytest.fail(f"Request failed: {data.get('error')}")

            await asyncio.sleep(2)
        else:
            pytest.fail("Liquidity risk request did not complete within 60 seconds")

        # Verify response structure
        assert "risk_score" in data
        assert 1 <= data["risk_score"] <= 10, f"risk_score should be 1-10, got {data['risk_score']}"

        assert "risk_level" in data
        assert data["risk_level"] in ["Low", "Medium", "High"], \
            f"risk_level should be Low/Medium/High, got {data['risk_level']}"

        # Check for correct field name
        assert "ar_concentration_risk" in data, "ar_concentration_risk field must be present"
        assert "concentration_risk" not in data, "Wrong field name: use ar_concentration_risk not concentration_risk"

    async def test_liquidity_risk_alerts(self, http_client):
        """
        GET /api/liquidity-risk/alerts
        Assert: 200, response is a list
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/liquidity-risk/alerts?entity_id=entity-test-001",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list), "alerts endpoint should return a list"

    async def test_liquidity_risk_unauthenticated_returns_401(self, http_client):
        """GET /api/liquidity-risk/alerts without token returns 401."""
        response = await http_client.get("/api/liquidity-risk/alerts")
        assert response.status_code == 401
