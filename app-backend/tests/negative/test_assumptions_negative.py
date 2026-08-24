"""
Negative tests for manual assumptions.
Tests: invalid amounts, past dates, confidence boundaries (>=50 critical), invalid categories.
"""
import pytest
import httpx
import datetime
from tests.jwt_helper import make_analyst_token, make_treasury_manager_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        yield client


class TestAssumptionsNegative:
    """Test manual assumptions validation."""

    @pytest.mark.asyncio
    async def test_d1_amount_zero_rejected(self, http_client):
        """D1: Amount = 0 returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": 0,
                "direction": "Inflow",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": 80
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "must be > 0" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_d2_amount_negative_rejected(self, http_client):
        """D2: Negative amount returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": -50000,
                "direction": "Inflow",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": 80
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "must be > 0" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_d3_past_date_rejected(self, http_client):
        """D3: Past date returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": 50000,
                "direction": "Inflow",
                "category": "Operating",
                "date": yesterday,
                "confidence_pct": 80
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "must be >=" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_d4_invalid_direction_rejected(self, http_client):
        """D4: Invalid direction returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": 50000,
                "direction": "Transfer",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": 80
            },
            headers=headers
        )

        assert response.status_code == 422
        data = response.json()
        assert "direction" in data.get("error", {}).get("message", "").lower()
        assert "Inflow" in data.get("error", {}).get("message", "")
        assert "Outflow" in data.get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_d5_invalid_category_rejected(self, http_client):
        """D5: Invalid category returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": 50000,
                "direction": "Inflow",
                "category": "Salary",
                "date": "2026-08-25",
                "confidence_pct": 80
            },
            headers=headers
        )

        assert response.status_code == 422
        data = response.json()
        assert "category" in data.get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_d6_confidence_below_zero_rejected(self, http_client):
        """D6: Confidence < 0 returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": 50000,
                "direction": "Inflow",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": -1
            },
            headers=headers
        )

        assert response.status_code == 422
        data = response.json()
        assert "confidence" in data.get("error", {}).get("message", "").lower()
        assert "0" in data.get("error", {}).get("message", "")
        assert "100" in data.get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_d7_confidence_above_100_rejected(self, http_client):
        """D7: Confidence > 100 returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": 50000,
                "direction": "Inflow",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": 101
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "100" in response.json().get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_d8_confidence_49_excluded_from_forecast(self, http_client):
        """D8: Confidence = 49 excluded from forecast calculations."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create assumption with 49% confidence
        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": 100000,
                "direction": "Inflow",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": 49
            },
            headers=headers
        )

        assert response.status_code in [200, 201]
        assumption_id = response.json().get("id")

        # Verify it's NOT included in forecast
        get_response = await http_client.get(
            f"/api/forecast/assumptions/{assumption_id}",
            headers=headers
        )

        if get_response.status_code == 200:
            assumption = get_response.json()
            assert assumption.get("included_in_forecast") == False

    @pytest.mark.asyncio
    async def test_d9_confidence_50_included_boundary(self, http_client):
        """D9: Confidence = 50 INCLUDED (boundary: >=50 not >50)."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create assumption with exactly 50% confidence
        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                "amount": 100000,
                "direction": "Inflow",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": 50
            },
            headers=headers
        )

        assert response.status_code in [200, 201]
        assumption_id = response.json().get("id")

        # Verify it IS included in forecast
        get_response = await http_client.get(
            f"/api/forecast/assumptions/{assumption_id}",
            headers=headers
        )

        if get_response.status_code == 200:
            assumption = get_response.json()
            assert assumption.get("included_in_forecast") == True

    @pytest.mark.asyncio
    async def test_d10_unknown_entity_id_rejected(self, http_client):
        """D10: Unknown entity_id returns 422 or 404."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "00000000-0000-0000-0000-000000000000",
                "amount": 50000,
                "direction": "Inflow",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": 80
            },
            headers=headers
        )

        assert response.status_code in [422, 404]
        assert "entity" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_d11_missing_required_field_amount(self, http_client):
        """D11: Missing 'amount' field returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/forecast/assumptions",
            json={
                "entity_id": "entity-test-001",
                # Missing amount
                "direction": "Inflow",
                "category": "Operating",
                "date": "2026-08-25",
                "confidence_pct": 80
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "amount" in response.json().get("error", {}).get("message", "").lower()
