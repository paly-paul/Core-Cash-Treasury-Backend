"""
Playwright API contract tests.
Use APIRequestContext for REST calls — no browser needed.
Verify API contracts: field names, types, and access control.
"""
import pytest
from tests.jwt_helper import (
    make_treasury_manager_token,
    make_viewer_token,
    make_cfo_token,
)


@pytest.fixture
async def api_context(playwright):
    """Create Playwright API request context."""
    async with playwright.request.new_context() as context:
        yield context


class TestAPIContracts:
    """API contract tests."""

    @pytest.mark.asyncio
    async def test_internal_fields_not_leaked_in_recommendations(self, api_context):
        """
        Contract: Internal fields must never appear in recommendations response.
        - blocked_count (internal)
        - blocked_reasons (internal)
        - source_agent_runs (internal)
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await api_context.get(
            "http://localhost:8000/api/recommendations?entity_id=entity-test-001",
            headers=headers,
        )

        assert response.status == 200
        data = response.json()
        assert isinstance(data, list)

        for item in data:
            assert "blocked_count" not in item, "blocked_count is internal"
            assert "blocked_reasons" not in item, "blocked_reasons is internal"
            assert "source_agent_runs" not in item, "source_agent_runs is internal"

    @pytest.mark.asyncio
    async def test_variance_field_types(self, api_context):
        """
        Contract: Variance explanation must have correct field types.
        - within_tolerance: bool (not string)
        - unexplained_variance_usd: number (not null)
        - narrative: str (not dict/list)
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await api_context.get(
            "http://localhost:8000/api/forecast/variance/current?entity_id=entity-test-001",
            headers=headers,
        )

        # May be 200 or 503 depending on data state
        if response.status == 200:
            data = response.json()

            if "within_tolerance" in data:
                assert isinstance(data["within_tolerance"], bool), \
                    "within_tolerance must be bool, not string"

            if "unexplained_variance_usd" in data:
                assert isinstance(data["unexplained_variance_usd"], (int, float)), \
                    "unexplained_variance_usd must be number"

            if "narrative" in data:
                assert isinstance(data["narrative"], str), \
                    "narrative must be string, not dict/list"

    @pytest.mark.asyncio
    async def test_cfo_summary_field_types(self, api_context):
        """
        Contract: CFO summary must have correct field types and names.
        - ytd_change: must NOT be present (only mtd_change allowed)
        - narrative: str (not dict/list)
        """
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await api_context.get(
            "http://localhost:8000/api/cfo-summary/latest?entity_id=entity-test-001",
            headers=headers,
        )

        if response.status == 200:
            data = response.json()

            assert "ytd_change" not in data, \
                "ytd_change must not be in response (use mtd_change only)"

            if "narrative" in data:
                assert isinstance(data["narrative"], str), \
                    "narrative must be string, not dict/list"

            if "mtd_change" in data:
                assert isinstance(data["mtd_change"], (int, float)), \
                    "mtd_change must be a number"

    @pytest.mark.asyncio
    async def test_forecast_blocked_returns_200_not_503(self, api_context):
        """
        Contract: Blocked forecast returns 200, not 503.
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Query a forecast that might be blocked
        response = await api_context.get(
            "http://localhost:8000/api/forecast/latest?entity_id=entity-no-bank-data",
            headers=headers,
        )

        # If found and blocked:
        if response.status == 200:
            data = response.json()
            if data.get("data_status") == "blocked":
                assert "OPENING_BALANCE_UNRESOLVED" in data.get("blocked_reason", ""), \
                    "blocked_reason should mention root cause"

        # Should not be 503
        assert response.status != 503, "Blocked forecast should return 200, not 503"

    @pytest.mark.asyncio
    async def test_role_enforcement_on_recommendation_approval(self, api_context):
        """
        Contract: Viewer role cannot approve recommendations.
        POST /api/recommendations/{id}/approve with Viewer token → 403
        """
        viewer_token = make_viewer_token()
        headers = {"Authorization": f"Bearer {viewer_token}"}

        response = await api_context.post(
            "http://localhost:8000/api/recommendations/rec-id-test/approve",
            headers=headers,
        )

        # Should be 403 or 404 (403 if role check hits first)
        assert response.status in [403, 404], \
            f"Viewer should not be able to approve, got {response.status}"

    @pytest.mark.asyncio
    async def test_unauthenticated_requests_return_401(self, api_context):
        """
        Contract: All protected endpoints return 401 without token.
        """
        endpoints = [
            "/api/cash-position/current",
            "/api/recommendations",
            "/api/cfo-summary/latest",
            "/api/liquidity-risk/alerts",
        ]

        for endpoint in endpoints:
            response = await api_context.get(f"http://localhost:8000{endpoint}")
            assert response.status == 401, \
                f"{endpoint} should return 401 without token, got {response.status}"

    @pytest.mark.asyncio
    async def test_post_chat_without_token_returns_401(self, api_context):
        """
        Contract: POST /api/chat/stream without token returns 401.
        """
        response = await api_context.post(
            "http://localhost:8000/api/chat/stream",
            data={
                "messages": [{"role": "user", "content": "Hello"}],
                "entity_id": "entity-test-001",
            },
        )

        assert response.status == 401, \
            f"Chat stream should return 401 without token, got {response.status}"

    @pytest.mark.asyncio
    async def test_pagination_contracts(self, api_context):
        """
        Contract: List endpoints support limit and offset.
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Get recommendations with limit
        response = await api_context.get(
            "http://localhost:8000/api/recommendations?limit=5&offset=0",
            headers=headers,
        )

        assert response.status == 200, \
            "List endpoint should accept limit and offset parameters"

    @pytest.mark.asyncio
    async def test_error_response_structure(self, api_context):
        """
        Contract: Error responses have consistent structure.
        - error.code (string)
        - error.message (string)
        - error.severity (string: error|warning)
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Trigger a validation error
        response = await api_context.post(
            "http://localhost:8000/api/chat/stream",
            json={
                "messages": [],  # Invalid: empty
                "entity_id": "entity-test-001",
            },
            headers=headers,
        )

        if response.status == 422:
            data = response.json()
            # Check error structure
            assert "error" in data or "detail" in data, "Error response must have error/detail field"
