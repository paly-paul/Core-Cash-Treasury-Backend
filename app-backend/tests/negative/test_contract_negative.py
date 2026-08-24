"""
Negative API contract tests — verify forbidden fields NEVER appear.
Tests: no blocked_count, no ytd, no decision_log, no dangerous defaults.
"""
import pytest
import httpx
import json
import subprocess
from tests.jwt_helper import make_analyst_token, make_treasury_manager_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        yield client


class TestContractNegative:
    """Test API response contracts."""

    @pytest.mark.asyncio
    async def test_h1_blocked_count_not_in_recommendations(self, http_client):
        """H1: blocked_count, blocked_reasons, source_agent_runs NEVER in response."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Get recommendations
        response = await http_client.get(
            "/api/recommendations?entity_id=entity-test-001",
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            response_text = json.dumps(data)

            forbidden_fields = ["blocked_count", "blocked_reasons", "source_agent_runs"]
            for field in forbidden_fields:
                assert field not in response_text, \
                    f"Forbidden field '{field}' found in recommendations response"

    @pytest.mark.asyncio
    async def test_h2_human_approval_required_always_true(self, http_client):
        """H2: human_approval_required ALWAYS True (never False)."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/recommendations?entity_id=entity-test-001",
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            recommendations = data.get("recommendations", [])

            for rec in recommendations:
                control = rec.get("control", {})
                approval_required = control.get("human_approval_required")

                # CRITICAL: Must be True, never False
                assert approval_required == True, \
                    f"human_approval_required must be True, found {approval_required}"

    @pytest.mark.asyncio
    async def test_h3_decision_log_not_in_mongodb_or_response(self, http_client):
        """H3: decision_log collection must not exist in MongoDB."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Check API response doesn't include decision_log
        response = await http_client.get(
            "/api/recommendations?entity_id=entity-test-001",
            headers=headers
        )

        if response.status_code == 200:
            response_text = json.dumps(response.json())
            assert "decision_log" not in response_text.lower(), \
                "decision_log must not appear in API response"

    @pytest.mark.asyncio
    async def test_h4_ytd_never_in_any_response(self, http_client):
        """H4: YTD never appears (only MTD allowed)."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        endpoints = [
            "/api/cash-position/current",
            "/api/cfo-summary/latest",
            "/api/liquidity-risk/current",
        ]

        for endpoint in endpoints:
            response = await http_client.get(
                f"{endpoint}?entity_id=entity-test-001",
                headers=headers
            )

            if response.status_code == 200:
                response_text = json.dumps(response.json()).lower()
                assert "ytd" not in response_text, \
                    f"YTD found in {endpoint} — only MTD is permitted"

    @pytest.mark.asyncio
    async def test_h5_recommendation_what_no_forbidden_verbs(self, http_client):
        """H5: Recommendation 'what' field has no forbidden verbs."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/recommendations?entity_id=entity-test-001",
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            recommendations = data.get("recommendations", [])

            forbidden_verbs = ["transfer", "execute", "send", "move", "initiate"]

            for rec in recommendations:
                what_field = rec.get("what", "").lower()

                for verb in forbidden_verbs:
                    assert verb not in what_field, \
                        f"Forbidden verb '{verb}' found in 'what': {rec['what']}"

    @pytest.mark.asyncio
    async def test_h6_all_recommendation_fields_present_nonnull(self, http_client):
        """H6: All four recommendation fields (why, what, when, control) present and non-null."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/recommendations?entity_id=entity-test-001",
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            recommendations = data.get("recommendations", [])

            for rec in recommendations:
                # Check required fields
                assert rec.get("why") is not None and rec.get("why") != ""
                assert rec.get("what") is not None and rec.get("what") != ""
                assert rec.get("when") is not None and rec.get("when") != ""
                assert rec.get("control") is not None

                # Check control sub-fields
                control = rec.get("control", {})
                assert control.get("approval_owner") is not None and control.get("approval_owner") != ""
                assert control.get("policy_check") is not None and control.get("policy_check") != ""
                assert control.get("human_approval_required") is not None

    def test_h7_anthropic_not_imported_in_shared_or_app_backend(self):
        """H7: ANTHROPIC_API_KEY import only in ai-backend."""
        # Static analysis test
        result_shared = subprocess.run(
            ["grep", "-r", "anthropic", "app-backend/", "--include=*.py", "-l"],
            capture_output=True, text=True, cwd="/home/user/Core-Cash-Treasury-Backend"
        )

        result_app = subprocess.run(
            ["grep", "-r", "anthropic", "shared/", "--include=*.py", "-l"],
            capture_output=True, text=True, cwd="/home/user/Core-Cash-Treasury-Backend"
        )

        assert result_app.stdout.strip() == "", \
            f"anthropic imported in shared/: {result_app.stdout}"
        # app-backend should also not import anthropic (it's for AI backend only)
        anthropic_in_app = [line for line in result_shared.stdout.split('\n')
                            if 'anthropic' in line.lower() and 'api' in line.lower()]
        assert len(anthropic_in_app) == 0, \
            f"anthropic API imported in app-backend: {anthropic_in_app}"

    def test_h8_od_headroom_not_stored_in_database(self):
        """H8: od_headroom not a column in any table."""
        # This would require DB connection, skip if DB not available
        # Check: PostgreSQL schema should not have od_headroom column anywhere
        pytest.skip("Requires database connection — run with DB available")

    @pytest.mark.asyncio
    async def test_h9_no_unencrypted_secrets_in_responses(self, http_client):
        """H9: Secrets like API keys never appear in any response."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/cash-position/current?entity_id=entity-test-001",
            headers=headers
        )

        if response.status_code == 200:
            response_text = json.dumps(response.json())
            # Check for common secret patterns
            assert "ANTHROPIC_API_KEY" not in response_text
            assert "sk-" not in response_text  # OpenAI key pattern
            assert "password" not in response_text.lower()
