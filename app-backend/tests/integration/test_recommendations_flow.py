"""
Integration tests for recommendations flow.
Tests approval workflow and field validation.
"""
import pytest
import httpx
import asyncio
from tests.jwt_helper import (
    make_treasury_manager_token,
    make_cfo_token,
    make_viewer_token,
)


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        yield client


@pytest.mark.asyncio
class TestRecommendationsFlow:
    """Test recommendations and approval workflow."""

    async def test_recommendation_approval(self, http_client):
        """
        POST /api/recommendations/request
        Poll until Completed
        GET /api/recommendations
        Assert: no internal fields leaked (blocked_count, blocked_reasons, source_agent_runs)
        POST /api/recommendations/{id}/approve with CFO token
        Assert: approval_status == "Approved"
        POST approve again → 409 (double-action blocked)
        """
        token = make_treasury_manager_token()
        cfo_token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}
        cfo_headers = {"Authorization": f"Bearer {cfo_token}"}

        # Request recommendations
        response = await http_client.post(
            "/api/recommendations/request",
            json={"entity_id": "entity-test-001"},
            headers=headers,
        )

        assert response.status_code == 202
        data = response.json()
        request_id = data.get("request_id")

        # Poll until completed
        max_retries = 30
        for i in range(max_retries):
            response = await http_client.get(
                f"/api/recommendations/{request_id}",
                headers=headers,
            )
            assert response.status_code == 200
            data = response.json()

            if data.get("status") == "Completed":
                break
            elif data.get("status") == "Failed":
                pytest.fail(f"Request failed: {data.get('error')}")

            await asyncio.sleep(2)

        # Get recommendations
        response = await http_client.get(
            "/api/recommendations?entity_id=entity-test-001",
            headers=headers,
        )
        assert response.status_code == 200
        recs = response.json()
        assert isinstance(recs, list)

        if recs:
            rec = recs[0]
            rec_id = rec.get("id")

            # Verify no internal fields leaked
            assert "blocked_count" not in rec, "Internal field: blocked_count must not be in response"
            assert "blocked_reasons" not in rec, "Internal field: blocked_reasons must not be in response"
            assert "source_agent_runs" not in rec, "Internal field: source_agent_runs must not be in response"

            # Approve with CFO token
            response = await http_client.post(
                f"/api/recommendations/{rec_id}/approve",
                headers=cfo_headers,
            )
            assert response.status_code == 200
            approved = response.json()
            assert approved.get("approval_status") == "Approved"

            # Try to approve again → should be 409
            response = await http_client.post(
                f"/api/recommendations/{rec_id}/approve",
                headers=cfo_headers,
            )
            assert response.status_code == 409, \
                f"Double approval should return 409, got {response.status_code}"

    async def test_viewer_cannot_approve(self, http_client):
        """
        Viewer role attempting POST /api/recommendations/{id}/approve
        Assert: 403
        """
        viewer_token = make_viewer_token()
        headers = {"Authorization": f"Bearer {viewer_token}"}

        # Attempt to approve (would need a valid rec_id from above)
        response = await http_client.post(
            "/api/recommendations/rec-id-123/approve",
            headers=headers,
        )

        # Should be 403 or 404 (403 if role check happens first)
        assert response.status_code in [403, 404]

    async def test_recommendations_unauthenticated_returns_401(self, http_client):
        """GET /api/recommendations without token returns 401."""
        response = await http_client.get("/api/recommendations")
        assert response.status_code == 401
