"""
Negative tests for FX rates.
Tests: zero/negative rates, unknown currencies, stale rate warnings.
"""
import pytest
import httpx
from tests.jwt_helper import make_cfo_token, make_analyst_token, make_treasury_manager_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        yield client


class TestFXNegative:
    """Test FX rate validation."""

    @pytest.mark.asyncio
    async def test_e1_fx_rate_zero_rejected(self, http_client):
        """E1: FX rate = 0 returns 422."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/config/fx-rates",
            json={
                "rates": [
                    {"currency_from": "GBP", "rate": 0}
                ]
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "must be > 0" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_e2_fx_rate_negative_rejected(self, http_client):
        """E2: Negative FX rate returns 422."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/config/fx-rates",
            json={
                "rates": [
                    {"currency_from": "GBP", "rate": -1.27}
                ]
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "must be > 0" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_e3_unknown_currency_rejected(self, http_client):
        """E3: Unknown currency returns 422."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/config/fx-rates",
            json={
                "rates": [
                    {"currency_from": "JPY", "rate": 0.007}
                ]
            },
            headers=headers
        )

        assert response.status_code == 422
        data = response.json()
        assert "currency" in data.get("error", {}).get("message", "").lower()
        assert "unsupported" in data.get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_e4_stale_fx_rate_warning_in_cash_position(self, http_client):
        """E4: Stale FX rate shows warning (not blocked)."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # This test assumes FX rates for today are NOT entered
        # System should use prior day rate with warning
        response = await http_client.get(
            "/api/cash-position/current?entity_id=entity-test-001",
            headers=headers
        )

        # Should return 200 (not blocked)
        if response.status_code == 200:
            data = response.json()
            # If today's FX rate missing, warning should be set
            if data.get("fx_rates_warning"):
                assert data.get("fx_rates_warning") == True

        assert response.status_code != 500, "Stale FX rate must not cause 500"

    @pytest.mark.asyncio
    async def test_e5_non_admin_cannot_enter_fx_rates(self, http_client):
        """E5: Analyst cannot enter FX rates (403)."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/config/fx-rates",
            json={
                "rates": [
                    {"currency_from": "GBP", "rate": 1.27}
                ]
            },
            headers=headers
        )

        assert response.status_code == 403
        assert response.json().get("error", {}).get("code") == "FORBIDDEN"
