"""
Integration tests for cash position flow.
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
class TestCashPositionFlow:
    """Test cash position request and polling."""

    async def test_cash_position_request_and_poll(self, http_client):
        """
        POST /api/cash-position/request → 202 with request_id
        Poll GET /api/cash-position/{request_id} until Completed
        Assert total_usable_cash_usd and od_headroom present and correct
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Request cash position
        response = await http_client.post(
            "/api/cash-position/request",
            json={"entity_id": "entity-test-001"},
            headers=headers,
        )

        assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
        data = response.json()
        assert "request_id" in data
        request_id = data["request_id"]

        # Poll until completed
        max_retries = 30  # 30 * 2 = 60 seconds
        for i in range(max_retries):
            response = await http_client.get(
                f"/api/cash-position/{request_id}",
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
            pytest.fail("Cash position request did not complete within 60 seconds")

        # Get current cash position
        response = await http_client.get(
            "/api/cash-position/current?entity_id=entity-test-001",
            headers=headers,
        )
        assert response.status_code == 200
        result = response.json()

        # Assertions
        assert "total_usable_cash_usd" in result
        assert result["total_usable_cash_usd"] > 0, "total_usable_cash_usd should be positive"
        assert "od_headroom" in result
        assert result["od_headroom"] > 0, "od_headroom should be positive"

        # od_headroom = od_limit - od_utilised_amount
        # od_limit = 2_000_000, od_utilised = 200_000
        # Expected od_headroom = 1_800_000
        expected_od_headroom = 1_800_000
        assert result["od_headroom"] == expected_od_headroom, \
            f"od_headroom should be {expected_od_headroom}, got {result['od_headroom']}"

        # od_headroom should NOT be added into total_usable_cash_usd
        # total_usable_cash should be latest balance (1_450_000)
        # not balance + od_headroom
        assert result["total_usable_cash_usd"] <= 1_500_000, \
            "total_usable_cash_usd should not include od_headroom"

    async def test_cash_position_unauthenticated_returns_401(self, http_client):
        """GET /api/cash-position/current without token returns 401."""
        response = await http_client.get("/api/cash-position/current?entity_id=entity-test-001")
        assert response.status_code == 401
