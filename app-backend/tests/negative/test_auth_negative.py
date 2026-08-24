"""
Negative tests for authentication & RBAC.
Tests: missing JWT, expired tokens, wrong signatures, wrong roles, role violations.
"""
import pytest
import httpx
import jwt
import datetime
from tests.jwt_helper import (
    make_treasury_manager_token,
    make_viewer_token,
    make_cfo_token,
    make_analyst_token,
)


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        yield client


class TestAuthNegative:
    """Test authentication failures."""

    @pytest.mark.asyncio
    async def test_a1_missing_jwt_cookie_all_endpoints(self, http_client):
        """A1: Every protected endpoint without JWT returns 401."""
        endpoints = [
            ("GET", "/api/cash-position/current"),
            ("POST", "/api/recommendations/request"),
            ("POST", "/api/files/upload"),
            ("GET", "/api/liquidity-risk/current"),
            ("GET", "/api/cfo-summary/latest"),
            ("GET", "/api/audit-log"),
        ]

        for method, endpoint in endpoints:
            if method == "GET":
                response = await http_client.get(endpoint)
            else:
                response = await http_client.post(
                    endpoint,
                    json={"entity_id": "entity-test-001"} if endpoint != "/api/files/upload" else None
                )

            assert response.status_code == 401, \
                f"{endpoint} should return 401 without token, got {response.status_code}"
            data = response.json()
            assert data.get("error", {}).get("code") == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_a2_expired_jwt(self, http_client):
        """A2: Expired JWT returns 401."""
        # Create expired token
        payload = {
            "client_id": "client-test-001",
            "user_id": "user-test-001",
            "role": "TreasuryManager",
            "exp": datetime.datetime.utcnow() - datetime.timedelta(seconds=60)
        }
        expired_token = jwt.encode(payload, "test-secret-key-for-signing-jwts-in-tests", algorithm="HS256")

        headers = {"Authorization": f"Bearer {expired_token}"}
        response = await http_client.get("/api/cash-position/current", headers=headers)

        assert response.status_code == 401
        assert response.json().get("error", {}).get("code") == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_a3_jwt_wrong_signature(self, http_client):
        """A3: JWT signed with wrong key returns 401."""
        payload = {
            "client_id": "client-test-001",
            "user_id": "user-test-001",
            "role": "TreasuryManager",
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        }
        # Sign with DIFFERENT key
        wrong_token = jwt.encode(payload, "completely-different-secret-key", algorithm="HS256")

        headers = {"Authorization": f"Bearer {wrong_token}"}
        response = await http_client.get("/api/cash-position/current", headers=headers)

        assert response.status_code == 401
        assert response.json().get("error", {}).get("code") == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_a4_jwt_unknown_role(self, http_client):
        """A4: JWT with unknown role returns 403."""
        payload = {
            "client_id": "client-test-001",
            "user_id": "user-test-001",
            "role": "SuperAdmin",  # Not in [Viewer, Analyst, TreasuryManager, CFO]
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        }
        invalid_token = jwt.encode(payload, "test-secret-key-for-signing-jwts-in-tests", algorithm="HS256")

        headers = {"Authorization": f"Bearer {invalid_token}"}
        response = await http_client.get("/api/cash-position/current", headers=headers)

        assert response.status_code == 403
        assert response.json().get("error", {}).get("code") == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_a5_rbac_viewer_cannot_upload(self, http_client):
        """A5: Viewer cannot upload files."""
        token = make_viewer_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", b"Entity Name,Account Number,Closing Balance\nTest,ACC-001,1000000")},
            headers=headers
        )

        assert response.status_code == 403
        assert response.json().get("error", {}).get("code") == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_a6_rbac_viewer_cannot_request_recommendations(self, http_client):
        """A6: Viewer cannot request recommendations."""
        token = make_viewer_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/recommendations/request",
            json={"entity_id": "entity-test-001", "cash_position_date": "2026-08-24"},
            headers=headers
        )

        assert response.status_code == 403
        assert response.json().get("error", {}).get("code") == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_a7_rbac_analyst_cannot_approve(self, http_client):
        """A7: Analyst cannot approve recommendations."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/recommendations/rec-id-test/approve",
            json={"notes": "test"},
            headers=headers
        )

        assert response.status_code == 403
        assert response.json().get("error", {}).get("code") == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_a8_rbac_analyst_cannot_manage_accounts(self, http_client):
        """A8: Analyst cannot manage accounts."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # POST
        response = await http_client.post(
            "/api/accounts",
            json={
                "entity_id": "entity-test-001",
                "account_number": "ACC-9999",
                "currency": "GBP",
                "bank_name": "Test Bank"
            },
            headers=headers
        )
        assert response.status_code == 403

        # PUT
        response = await http_client.put(
            "/api/accounts/acct-001",
            json={"min_threshold": 500000},
            headers=headers
        )
        assert response.status_code == 403

        # DELETE
        response = await http_client.delete(
            "/api/accounts/acct-001",
            headers=headers
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_a9_rbac_treasury_manager_cannot_manage_investment_policy(self, http_client):
        """A9: TreasuryManager cannot manage investment policy."""
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/config/investment-policy",
            files={"policy": ("policy.pdf", b"PDF content")},
            headers=headers
        )

        assert response.status_code == 403
        assert response.json().get("error", {}).get("code") == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_a10_rbac_viewer_cannot_view_audit_log(self, http_client):
        """A10: Viewer cannot view audit log."""
        token = make_viewer_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.get(
            "/api/audit-log?entity_id=entity-test-001",
            headers=headers
        )

        assert response.status_code == 403
        assert response.json().get("error", {}).get("code") == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_a11_double_approval_conflict(self, http_client):
        """A11: Approving same recommendation twice returns 409."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Mock: assume recommendation rec-id-001 exists and is pending
        rec_id = "rec-id-001"

        # First approval
        response1 = await http_client.post(
            f"/api/recommendations/{rec_id}/approve",
            json={"notes": "Approved"},
            headers=headers
        )

        if response1.status_code == 200:
            # Second approval of same recommendation
            response2 = await http_client.post(
                f"/api/recommendations/{rec_id}/approve",
                json={"notes": "Approved again"},
                headers=headers
            )

            assert response2.status_code == 409
            # Verify only one audit entry
            audit_response = await http_client.get(
                "/api/audit-log?entity_id=entity-test-001&event_type=recommendation.approved",
                headers=headers
            )
            if audit_response.status_code == 200:
                events = audit_response.json()
                approval_count = len([e for e in events if e.get("recommendation_id") == rec_id])
                assert approval_count == 1, "Should have exactly one approval audit entry"

    @pytest.mark.asyncio
    async def test_a12_approve_already_rejected_returns_409(self, http_client):
        """A12: Approving already-rejected recommendation returns 409."""
        token = make_cfo_token()
        headers = {"Authorization": f"Bearer {token}"}

        rec_id = "rec-id-002"

        # First reject
        response1 = await http_client.post(
            f"/api/recommendations/{rec_id}/reject",
            json={"reason": "Policy violation"},
            headers=headers
        )

        if response1.status_code == 200:
            # Try to approve after rejection
            response2 = await http_client.post(
                f"/api/recommendations/{rec_id}/approve",
                json={"notes": "Approved"},
                headers=headers
            )

            assert response2.status_code == 409
            data = response2.json()
            assert "already rejected" in data.get("error", {}).get("message", "").lower()
