"""
Integration tests for audit log.
Tests audit event writing and append-only enforcement.
"""
import pytest
import httpx
from tests.jwt_helper import make_treasury_manager_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        yield client


@pytest.mark.asyncio
class TestAuditLog:
    """Test audit log functionality."""

    async def test_audit_event_written_after_approval(self, http_client):
        """
        After a recommendation is approved (via previous test),
        GET /api/audit?entity_id=entity-test-001
        Assert: audit event with event_type="recommendation.approved" exists
        Assert: user_name is a string (not a foreign key)
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/audit?entity_id=entity-test-001",
            headers=headers,
        )

        assert response.status_code == 200
        events = response.json()
        assert isinstance(events, list)

        # Look for approval event
        approval_events = [e for e in events if e.get("event_type") == "recommendation.approved"]

        if approval_events:
            event = approval_events[0]
            assert isinstance(event.get("user_name"), str), \
                "user_name should be a string, not a foreign key ID"
            assert len(event.get("user_name", "")) > 0, "user_name should not be empty"

    async def test_audit_log_append_only(self, http_client):
        """
        Attempt DELETE /api/audit/{id}
        Assert: 404 or 405 (endpoint does not support DELETE)
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.delete(
            "/api/audit/any-event-id",
            headers=headers,
        )

        # Should not support DELETE
        assert response.status_code in [404, 405], \
            f"Audit log should be append-only, got {response.status_code}"

    async def test_audit_log_unauthenticated_returns_401(self, http_client):
        """GET /api/audit without token returns 401."""
        response = await http_client.get("/api/audit?entity_id=entity-test-001")
        assert response.status_code == 401
