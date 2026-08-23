"""Tests for Liquidity Risk endpoints."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from fastapi.testclient import TestClient


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    return MagicMock(
        id="user-123",
        client_id="client-456",
        email="test@example.com",
        role="TreasuryManager",
    )


@pytest.fixture
def client_with_auth(app, mock_user):
    """FastAPI test client with mocked auth."""
    test_client = TestClient(app)

    def mock_get_current_user():
        return mock_user

    app.dependency_overrides[mock_get_current_user] = lambda: mock_user
    return test_client


class TestLiquidityRiskRequest:
    """Tests for POST /api/liquidity-risk/request."""

    @pytest.mark.asyncio
    async def test_request_returns_202_and_job_id(self, client_with_auth, mock_user):
        """POST request should return 202 with request_id."""
        response = client_with_auth.post("/api/liquidity-risk/request")

        assert response.status_code == 202
        body = response.json()
        assert "request_id" in body
        assert body["status"] == "queued"
        assert "queued_at" in body
        assert body["request_id"] != ""

    @pytest.mark.asyncio
    async def test_request_creates_job_status(self, client_with_auth, db_session):
        """POST request should create job_status record."""
        response = client_with_auth.post("/api/liquidity-risk/request")
        assert response.status_code == 202
        request_id = response.json()["request_id"]

        # Verify job_status was created
        from sqlalchemy import select
        from app.models.job_status import JobStatus

        stmt = select(JobStatus).where(JobStatus.job_id == request_id)
        result = await db_session.execute(stmt)
        job = result.scalar()

        assert job is not None
        assert job.job_type == "liquidity_risk"
        assert job.status == "queued"


class TestLiquidityRiskPoll:
    """Tests for GET /api/liquidity-risk/{request_id}."""

    @pytest.mark.asyncio
    async def test_poll_pending_job(self, client_with_auth, db_session):
        """GET with pending status should return status only."""
        from datetime import datetime
        from app.models.job_status import JobStatus
        from uuid import uuid4

        # Create a pending job
        job_id = str(uuid4())
        job = JobStatus(
            client_id="client-456",
            job_id=job_id,
            job_type="liquidity_risk",
            status="queued",
            requested_by="user-123",
            requested_at=datetime.utcnow(),
        )
        db_session.add(job)
        await db_session.commit()

        response = client_with_auth.get(f"/api/liquidity-risk/{job_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["request_id"] == job_id
        assert body["status"] == "queued"
        assert "queued_at" in body
        # Should NOT include full output when pending
        assert "risk_score" not in body

    @pytest.mark.asyncio
    async def test_poll_completed_job_returns_full_output(
        self, client_with_auth, db_session, mock_user
    ):
        """GET with completed status should return full Agent 3 output."""
        from datetime import datetime
        from app.models.job_status import JobStatus
        from uuid import uuid4
        from unittest.mock import AsyncMock

        job_id = str(uuid4())
        result_id = str(ObjectId())

        # Create a completed job
        job = JobStatus(
            client_id=mock_user.client_id,
            job_id=job_id,
            job_type="liquidity_risk",
            status="completed",
            requested_by=mock_user.id,
            requested_at=datetime.utcnow(),
            result_id=result_id,
        )
        db_session.add(job)
        await db_session.commit()

        # Mock MongoDB response
        with patch("app.routes.liquidity_risk.get_mongo_db") as mock_get_mongo:
            mock_collection = AsyncMock()
            mock_doc = {
                "_id": ObjectId(result_id),
                "client_id": str(mock_user.client_id),
                "agent": "liquidity_risk",
                "risk_score": 5,
                "risk_level": "Medium",
            }
            mock_collection.find_one = AsyncMock(return_value=mock_doc)
            mock_get_mongo.return_value = {"agent_runs": mock_collection}

            response = client_with_auth.get(f"/api/liquidity-risk/{job_id}")

            assert response.status_code == 200
            body = response.json()
            assert body["risk_score"] == 5
            assert body["risk_level"] == "Medium"

    @pytest.mark.asyncio
    async def test_poll_nonexistent_job(self, client_with_auth):
        """GET for nonexistent job should return 404."""
        response = client_with_auth.get("/api/liquidity-risk/nonexistent-id")
        assert response.status_code == 404


class TestLiquidityRiskCurrent:
    """Tests for GET /api/liquidity-risk/current."""

    @pytest.mark.asyncio
    async def test_current_no_run_exists(self, client_with_auth, mock_user):
        """GET current with no run should return 404."""
        with patch("app.routes.liquidity_risk.get_mongo_db") as mock_get_mongo:
            mock_collection = AsyncMock()
            mock_collection.find_one = AsyncMock(return_value=None)
            mock_get_mongo.return_value = {"agent_runs": mock_collection}

            response = client_with_auth.get("/api/liquidity-risk/current")

            assert response.status_code == 404
            body = response.json()
            assert body["error"]["code"] == "NOT_FOUND"
            assert "Request one via POST" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_current_returns_latest_run(self, client_with_auth, mock_user):
        """GET current should return latest completed run."""
        with patch("app.routes.liquidity_risk.get_mongo_db") as mock_get_mongo:
            mock_collection = AsyncMock()
            mock_doc = {
                "_id": ObjectId(),
                "client_id": str(mock_user.client_id),
                "agent": "liquidity_risk",
                "as_of": "2026-08-22T09:00:00Z",
                "risk_score": 3,
                "risk_level": "Low",
                "active_breaches": [],
                "ar_concentration_risk": {
                    "top_3_share_pct": 45.0,
                    "threshold_pct": 70.0,
                    "breached": False,
                    "high_single_counterparty": False,
                    "top_counterparties": [],
                },
                "stale_feeds": [],
                "narrative": "Liquidity risk is Low.",
            }
            mock_collection.find_one = AsyncMock(return_value=mock_doc)
            mock_get_mongo.return_value = {"agent_runs": mock_collection}

            response = client_with_auth.get("/api/liquidity-risk/current")

            assert response.status_code == 200
            body = response.json()
            assert body["risk_score"] == 3
            assert body["risk_level"] == "Low"
            # Verify ar_concentration_risk field exists (not concentration_risk)
            assert "ar_concentration_risk" in body
            assert "concentration_risk" not in body


class TestLiquidityRiskAlerts:
    """Tests for GET /api/liquidity-risk/alerts."""

    @pytest.mark.asyncio
    async def test_alerts_returns_critical_subset(self, client_with_auth, mock_user):
        """GET alerts should return only critical fields."""
        with patch("app.routes.liquidity_risk.get_mongo_db") as mock_get_mongo:
            mock_collection = AsyncMock()
            mock_doc = {
                "_id": ObjectId(),
                "client_id": str(mock_user.client_id),
                "agent": "liquidity_risk",
                "as_of": "2026-08-22T09:00:00Z",
                "risk_score": 7,
                "risk_level": "High",
                "score_breakdown": {
                    "base": 1,
                    "breach_points": 6,
                    "stale_feed_points": 0,
                    "ar_concentration_points": 0,
                    "shortfall_points": 0,
                    "raw_total": 7,
                    "capped": False,
                },
                "active_breaches": [
                    {
                        "entity_name": "US HQ",
                        "account_name": "JPM USD Main",
                        "min_threshold": 2000000,
                        "current_balance": 1500000,
                        "shortfall": 500000,
                        "currency": "USD",
                    }
                ],
                "forecast_shortfall_days": [],
                "ar_concentration_risk": {
                    "top_3_share_pct": 50.0,
                    "threshold_pct": 70.0,
                    "breached": False,
                    "high_single_counterparty": False,
                    "top_counterparties": [],
                },
                "stale_feeds": [],
                "narrative": "Liquidity risk is High.",
            }
            mock_collection.find_one = AsyncMock(return_value=mock_doc)
            mock_get_mongo.return_value = {"agent_runs": mock_collection}

            response = client_with_auth.get("/api/liquidity-risk/alerts")

            assert response.status_code == 200
            body = response.json()

            # Should only include specific fields
            assert "as_of" in body
            assert body["as_of"] == "2026-08-22T09:00:00Z"
            assert body["risk_level"] == "High"
            assert "critical_breaches" in body
            assert len(body["critical_breaches"]) == 1
            assert body["critical_breaches"][0]["account_name"] == "JPM USD Main"
            assert "forecast_shortfall_days" in body
            assert body["forecast_shortfall_days"] == []

            # Should NOT include these fields
            assert "risk_score" not in body
            assert "score_breakdown" not in body
            assert "ar_concentration_risk" not in body
            assert "narrative" not in body

    @pytest.mark.asyncio
    async def test_alerts_no_run_exists(self, client_with_auth):
        """GET alerts with no run should return 404."""
        with patch("app.routes.liquidity_risk.get_mongo_db") as mock_get_mongo:
            mock_collection = AsyncMock()
            mock_collection.find_one = AsyncMock(return_value=None)
            mock_get_mongo.return_value = {"agent_runs": mock_collection}

            response = client_with_auth.get("/api/liquidity-risk/alerts")

            assert response.status_code == 404
