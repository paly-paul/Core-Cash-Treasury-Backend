"""
Negative tests for Account Master.
Tests: duplicate accounts, invalid thresholds, unknown entities, read-only fields.
"""
import pytest
import httpx
import uuid
from tests.jwt_helper import make_cfo_token, make_treasury_manager_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        yield client


class TestAccountsNegative:
    """Test account management validation."""

    @pytest.mark.asyncio
    async def test_c1_duplicate_account_number_same_client(self, http_client):
        """C1: Duplicate account_number for same client returns 409."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Try to create duplicate ACC-001 (already exists from test seed)
        response = await http_client.post(
            "/api/accounts",
            json={
                "entity_id": "entity-test-001",
                "account_number": "ACC-001",  # Already exists
                "currency": "GBP",
                "bank_name": "Test Bank",
                "account_type": "Operating"
            },
            headers=headers
        )

        assert response.status_code == 409
        assert "already exists" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_c2_negative_min_threshold(self, http_client):
        """C2: Negative min_threshold returns 422."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/accounts",
            json={
                "entity_id": "entity-test-001",
                "account_number": "ACC-NEW-1",
                "currency": "GBP",
                "bank_name": "Test Bank",
                "min_threshold": -500000
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "min_threshold" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_c3_negative_od_limit(self, http_client):
        """C3: Negative od_limit returns 422."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/accounts",
            json={
                "entity_id": "entity-test-001",
                "account_number": "ACC-NEW-2",
                "currency": "GBP",
                "bank_name": "Test Bank",
                "od_limit": -100000
            },
            headers=headers
        )

        assert response.status_code == 422
        assert "od_limit" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_c4_unknown_entity_id(self, http_client):
        """C4: Unknown entity_id returns 422 or 404."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await http_client.post(
            "/api/accounts",
            json={
                "entity_id": fake_id,
                "account_number": "ACC-NEW-3",
                "currency": "GBP",
                "bank_name": "Test Bank"
            },
            headers=headers
        )

        assert response.status_code in [422, 404]
        assert "entity" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_c5_unsupported_currency(self, http_client):
        """C5: Unsupported currency returns 422."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/accounts",
            json={
                "entity_id": "entity-test-001",
                "account_number": "ACC-NEW-4",
                "currency": "CHF",
                "bank_name": "Test Bank"
            },
            headers=headers
        )

        assert response.status_code == 422
        data = response.json()
        assert "currency" in data.get("error", {}).get("message", "").lower()
        # Should list supported currencies
        assert "USD" in data.get("error", {}).get("message", "") or "GBP" in data.get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_c6_invalid_refresh_frequency(self, http_client):
        """C6: Invalid refresh_frequency returns 422."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/accounts",
            json={
                "entity_id": "entity-test-001",
                "account_number": "ACC-NEW-5",
                "currency": "GBP",
                "bank_name": "Test Bank",
                "refresh_frequency": "Hourly"  # Invalid, should be Daily or Manual
            },
            headers=headers
        )

        assert response.status_code == 422
        data = response.json()
        assert "refresh_frequency" in data.get("error", {}).get("message", "").lower()
        assert "Daily" in data.get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_c7_edit_read_only_field_account_number(self, http_client):
        """C7: Editing account_number is ignored or returns error."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        # First, create an account
        create_response = await http_client.post(
            "/api/accounts",
            json={
                "entity_id": "entity-test-001",
                "account_number": "ACC-READONLY-1",
                "currency": "GBP",
                "bank_name": "Test Bank"
            },
            headers=headers
        )

        if create_response.status_code in [200, 201]:
            account_id = create_response.json().get("id")

            # Try to edit account_number
            update_response = await http_client.put(
                f"/api/accounts/{account_id}",
                json={"account_number": "ACC-CHANGED"},
                headers=headers
            )

            if update_response.status_code == 422:
                assert "read-only" in update_response.json().get("error", {}).get("message", "").lower()
            else:
                # Verify account_number was NOT changed
                get_response = await http_client.get(f"/api/accounts/{account_id}", headers=headers)
                if get_response.status_code == 200:
                    assert get_response.json().get("account_number") == "ACC-READONLY-1"

    @pytest.mark.asyncio
    async def test_c8_delete_nonexistent_account(self, http_client):
        """C8: Delete non-existent account returns 404."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await http_client.delete(f"/api/accounts/{fake_id}", headers=headers)

        assert response.status_code == 404
        assert response.json().get("error", {}).get("code") == "NOT_FOUND"
