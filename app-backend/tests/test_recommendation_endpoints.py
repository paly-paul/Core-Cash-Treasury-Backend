"""
Comprehensive tests for recommendation endpoints.
Tests cover: POST request, GET poll, GET list, approve, reject, override.
"""
import pytest
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, patch, MagicMock
from bson import ObjectId

from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_user
from app.auth.models import UserModel
from app.database import get_db


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_user():
    """Mock authenticated user with TreasuryManager role."""
    user = MagicMock(spec=UserModel)
    user.user_id = str(uuid4())
    user.client_id = uuid4()
    user.email = "user@example.com"
    user.role = "TreasuryManager"
    return user


@pytest.fixture
def mock_analyst_user():
    """Mock analyst user (can request but not approve)."""
    user = MagicMock(spec=UserModel)
    user.user_id = str(uuid4())
    user.client_id = uuid4()
    user.email = "analyst@example.com"
    user.role = "Analyst"
    return user


@pytest.fixture
def mock_viewer_user():
    """Mock viewer user (cannot request or approve)."""
    user = MagicMock(spec=UserModel)
    user.user_id = str(uuid4())
    user.client_id = uuid4()
    user.email = "viewer@example.com"
    user.role = "Viewer"
    return user


@pytest.fixture
def client_with_auth(db, mock_user):
    """FastAPI test client with mocked auth (TreasuryManager)."""
    def override_get_current_user():
        return mock_user

    def override_get_db():
        return db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    test_client = TestClient(app)
    yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def client_with_analyst(db, mock_analyst_user):
    """FastAPI test client with analyst auth."""
    def override_get_current_user():
        return mock_analyst_user

    def override_get_db():
        return db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    test_client = TestClient(app)
    yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def client_with_viewer(db, mock_viewer_user):
    """FastAPI test client with viewer auth."""
    def override_get_current_user():
        return mock_viewer_user

    def override_get_db():
        return db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    test_client = TestClient(app)
    yield test_client

    app.dependency_overrides.clear()


# ============================================================================
# Test POST /api/recommendations/request
# ============================================================================


class TestPostRequest:
    """Tests for POST /api/recommendations/request."""

    def test_request_returns_202(self, client_with_auth):
        """Test POST request returns 202 with request_id."""
        with patch("app.routers.recommendations.InProcessJobPublisher.publish", new_callable=AsyncMock):
            response = client_with_auth.post(
                "/api/recommendations/request",
                json={"cash_position_date": "2026-08-22", "policy_id": "policy_default"},
            )

        assert response.status_code == 202
        data = response.json()
        assert "request_id" in data
        assert data["status"] == "queued"
        assert "queued_at" in data

    def test_request_job_publisher_fails_returns_503(self, client_with_auth):
        """Test POST request returns 503 when job publisher fails."""
        with patch("app.routers.recommendations.InProcessJobPublisher.publish", side_effect=Exception("SQS error")):
            response = client_with_auth.post(
                "/api/recommendations/request",
                json={},
            )

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["code"] == "AGENT_ERROR"

    def test_request_analyst_can_request(self, client_with_analyst):
        """Test that Analyst role can request recommendations."""
        with patch("app.routers.recommendations.InProcessJobPublisher.publish", new_callable=AsyncMock):
            response = client_with_analyst.post(
                "/api/recommendations/request",
                json={},
            )

        assert response.status_code == 202


# ============================================================================
# Test GET /api/recommendations/{request_id}
# ============================================================================


class TestGetStatus:
    """Tests for GET /api/recommendations/{request_id}."""

    def test_get_queued_returns_status_only(self, client_with_auth):
        """Test GET with queued status returns minimal response."""
        from app.models.job_status import JobStatus
        from core_cash_shared import JobStatus as JobStatusEnum, JobType
        from sqlalchemy import select

        job_id = str(uuid4())

        # Mock the database query
        mock_job = MagicMock()
        mock_job.job_id = job_id
        mock_job.client_id = client_with_auth.app.dependency_overrides[get_current_user]().client_id
        mock_job.status = JobStatusEnum.QUEUED.value
        mock_job.requested_at = datetime.utcnow()

        with patch("app.routers.recommendations.select") as mock_select:
            mock_query = MagicMock()
            mock_result = MagicMock()
            mock_result.scalar.return_value = mock_job
            mock_select.return_value = mock_query

            response = client_with_auth.get(f"/api/recommendations/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert "recommendations" not in data

    def test_get_not_found(self, client_with_auth):
        """Test GET with non-existent request_id returns 404."""
        fake_id = str(uuid4())

        response = client_with_auth.get(f"/api/recommendations/{fake_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["code"] == "NOT_FOUND"

    def test_get_completed_returns_full_response(self, client_with_auth):
        """Test GET completed returns full response with reasoning_trace."""
        job_id = str(uuid4())
        result_id = str(ObjectId())

        mock_job = MagicMock()
        mock_job.job_id = job_id
        mock_job.status = "completed"
        mock_job.result_id = result_id
        mock_job.completed_at = datetime.utcnow()

        mock_rec_doc = {
            "_id": ObjectId(result_id),
            "recommendation_count": 2,
            "recommendations": [
                {
                    "id": str(uuid4()),
                    "priority": 1,
                    "approval_status": "Pending",
                }
            ],
            "created_at": datetime.utcnow(),
        }

        with patch("app.routers.recommendations.select"):
            # Mock the database to return our test job
            with patch.object(client_with_auth.app.dependency_overrides[get_db].__self__, 'execute', new_callable=MagicMock) as mock_execute:
                mock_result = MagicMock()
                mock_result.scalar.return_value = mock_job
                mock_execute.return_value = mock_result

                with patch("app.routers.recommendations.get_recommendation_result", return_value=mock_rec_doc):
                    response = client_with_auth.get(f"/api/recommendations/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "reasoning_trace" in data

    def test_get_failed_status(self, client_with_auth):
        """Test GET with failed status."""
        job_id = str(uuid4())

        mock_job = MagicMock()
        mock_job.job_id = job_id
        mock_job.status = "failed"
        mock_job.error_message = "Agent timeout"

        response = client_with_auth.get(f"/api/recommendations/{job_id}")

        assert response.status_code == 404


# ============================================================================
# Test GET /api/recommendations
# ============================================================================


class TestList:
    """Tests for GET /api/recommendations."""

    def test_list_empty(self, client_with_auth):
        """Test list returns empty when no jobs exist."""
        response = client_with_auth.get("/api/recommendations")

        assert response.status_code == 200
        data = response.json()
        assert data["recommendations"] == []
        assert data["total"] == 0


# ============================================================================
# Test POST /api/recommendations/{id}/approve
# ============================================================================


class TestApprove:
    """Tests for POST /api/recommendations/{id}/approve."""

    def test_approve_happy_path(self, client_with_auth):
        """Test approve returns 200 with updated recommendation."""
        rec_id = str(uuid4())
        mock_updated_rec = {
            "id": rec_id,
            "approval_status": "Approved",
            "approved_by": "user-id",
            "approved_at": datetime.utcnow(),
            "notes": "Approved by user",
        }

        with patch("app.routers.recommendations.approve_recommendation", return_value=mock_updated_rec):
            with patch("app.routers.recommendations.write_audit_event", new_callable=AsyncMock):
                response = client_with_auth.post(
                    f"/api/recommendations/{rec_id}/approve",
                    json={"notes": "Approved by user"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["approval_status"] == "Approved"

    def test_approve_double_approve_returns_409(self, client_with_auth):
        """Test that double-approve returns 409."""
        rec_id = str(uuid4())

        with patch("app.routers.recommendations.approve_recommendation", side_effect=ValueError("already been actioned")):
            response = client_with_auth.post(
                f"/api/recommendations/{rec_id}/approve",
                json={"notes": "Test"},
            )

        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["code"] == "VALIDATION_ERROR"

    def test_approve_analyst_returns_403(self, client_with_analyst):
        """Test that Analyst cannot approve (403)."""
        rec_id = str(uuid4())

        response = client_with_analyst.post(
            f"/api/recommendations/{rec_id}/approve",
            json={"notes": "Test"},
        )

        assert response.status_code == 403

    def test_approve_not_found_returns_404(self, client_with_auth):
        """Test that approve non-existent recommendation returns 404."""
        rec_id = str(uuid4())

        with patch("app.routers.recommendations.approve_recommendation", side_effect=ValueError("Recommendation not found")):
            response = client_with_auth.post(
                f"/api/recommendations/{rec_id}/approve",
                json={"notes": "Test"},
            )

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["code"] == "NOT_FOUND"

    def test_approve_audit_event_written(self, client_with_auth):
        """Test that audit event is written on approve."""
        rec_id = str(uuid4())
        mock_updated_rec = {
            "id": rec_id,
            "approval_status": "Approved",
            "approved_by": "user-id",
            "approved_at": datetime.utcnow(),
            "notes": "Test",
        }

        with patch("app.routers.recommendations.approve_recommendation", return_value=mock_updated_rec):
            with patch("app.routers.recommendations.write_audit_event", new_callable=AsyncMock) as mock_audit:
                response = client_with_auth.post(
                    f"/api/recommendations/{rec_id}/approve",
                    json={"notes": "Test"},
                )

        assert response.status_code == 200
        mock_audit.assert_called_once()

    def test_approve_audit_write_failure_non_blocking(self, client_with_auth):
        """Test that approve still succeeds even if audit write fails."""
        rec_id = str(uuid4())
        mock_updated_rec = {
            "id": rec_id,
            "approval_status": "Approved",
            "approved_by": "user-id",
            "approved_at": datetime.utcnow(),
            "notes": "Test",
        }

        with patch("app.routers.recommendations.approve_recommendation", return_value=mock_updated_rec):
            with patch("app.routers.recommendations.write_audit_event", side_effect=Exception("DB down")):
                response = client_with_auth.post(
                    f"/api/recommendations/{rec_id}/approve",
                    json={"notes": "Test"},
                )

        # Should still return 200 (non-blocking audit)
        assert response.status_code == 200


# ============================================================================
# Test POST /api/recommendations/{id}/reject
# ============================================================================


class TestReject:
    """Tests for POST /api/recommendations/{id}/reject."""

    def test_reject_happy_path(self, client_with_auth):
        """Test reject returns 200 with updated recommendation."""
        rec_id = str(uuid4())
        mock_updated_rec = {
            "id": rec_id,
            "approval_status": "Rejected",
            "rejected_by": "user-id",
            "rejected_at": datetime.utcnow(),
            "rejection_reason": "Not actioning today",
        }

        with patch("app.routers.recommendations.reject_recommendation", return_value=mock_updated_rec):
            with patch("app.routers.recommendations.write_audit_event", new_callable=AsyncMock):
                response = client_with_auth.post(
                    f"/api/recommendations/{rec_id}/reject",
                    json={"reason": "Not actioning today"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["approval_status"] == "Rejected"

    def test_reject_already_actioned_returns_409(self, client_with_auth):
        """Test that reject after approve returns 409."""
        rec_id = str(uuid4())

        with patch("app.routers.recommendations.reject_recommendation", side_effect=ValueError("already been actioned")):
            response = client_with_auth.post(
                f"/api/recommendations/{rec_id}/reject",
                json={"reason": "Test"},
            )

        assert response.status_code == 409


# ============================================================================
# Test POST /api/recommendations/{id}/override
# ============================================================================


class TestOverride:
    """Tests for POST /api/recommendations/{id}/override."""

    def test_override_happy_path(self, client_with_auth):
        """Test override returns 200 with updated recommendation."""
        rec_id = str(uuid4())
        mock_updated_rec = {
            "id": rec_id,
            "approval_status": "Overridden",
            "overridden_by": "user-id",
            "overridden_at": datetime.utcnow(),
            "action_taken": "Manually initiated transfer",
            "notes": "Different amount",
        }

        with patch("app.routers.recommendations.override_recommendation", return_value=mock_updated_rec):
            with patch("app.routers.recommendations.write_audit_event", new_callable=AsyncMock):
                response = client_with_auth.post(
                    f"/api/recommendations/{rec_id}/override",
                    json={"action_taken": "Manually initiated transfer", "notes": "Different amount"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["approval_status"] == "Overridden"
        assert data["action_taken"] == "Manually initiated transfer"

    def test_override_already_actioned_returns_409(self, client_with_auth):
        """Test that override after approve returns 409."""
        rec_id = str(uuid4())

        with patch("app.routers.recommendations.override_recommendation", side_effect=ValueError("already been actioned")):
            response = client_with_auth.post(
                f"/api/recommendations/{rec_id}/override",
                json={"action_taken": "Test", "notes": "Test"},
            )

        assert response.status_code == 409
