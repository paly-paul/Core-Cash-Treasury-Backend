"""Tests for Liquidity Risk endpoints."""
import pytest
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from bson import ObjectId

from app.main import app
from app.models.job_status import JobStatus
from app.auth.dependencies import get_current_user
from app.auth.models import UserModel


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    user = MagicMock(spec=UserModel)
    user.id = uuid4()
    user.client_id = uuid4()
    user.email = "test@example.com"
    user.role = "TreasuryManager"
    return user


@pytest.fixture
def client_with_auth(db, mock_user):
    """FastAPI test client with mocked auth."""
    from app.database import get_db

    def override_get_current_user():
        return mock_user

    def override_get_db():
        return db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    test_client = TestClient(app)
    yield test_client

    app.dependency_overrides.clear()


class TestLiquidityRiskRequest:
    """Tests for POST /api/liquidity-risk/request."""

    def test_request_returns_202_and_job_id(self, client_with_auth, mock_user):
        """POST request should return 202 with request_id."""
        response = client_with_auth.post("/api/liquidity-risk/request")

        assert response.status_code == 202
        body = response.json()
        assert "request_id" in body
        assert body["status"] == "queued"
        assert "queued_at" in body
        assert body["request_id"] != ""


class TestLiquidityRiskPoll:
    """Tests for GET /api/liquidity-risk/{request_id}."""

    def test_poll_nonexistent_job(self, client_with_auth):
        """GET for nonexistent job should return 404."""
        response = client_with_auth.get("/api/liquidity-risk/nonexistent-id")
        assert response.status_code == 404


class TestLiquidityRiskCurrent:
    """Tests for GET /api/liquidity-risk/current."""

    def test_current_no_run_exists(self, client_with_auth, mock_user):
        """GET current with no run should return 404."""
        with patch("app.routes.liquidity_risk.get_mongo_db") as mock_get_mongo:
            mock_collection = AsyncMock()
            mock_collection.find_one = AsyncMock(return_value=None)
            mock_mongo_db = MagicMock()
            mock_mongo_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_get_mongo.return_value = mock_mongo_db

            response = client_with_auth.get("/api/liquidity-risk/current")

            assert response.status_code == 404
            body = response.json()
            assert body["error"]["code"] == "NOT_FOUND"
            assert "Request one via POST" in body["error"]["message"]

    def test_current_returns_latest_run(self, client_with_auth, mock_user):
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
            mock_mongo_db = MagicMock()
            mock_mongo_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_get_mongo.return_value = mock_mongo_db

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

    def test_alerts_returns_critical_subset(self, client_with_auth, mock_user):
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
            mock_mongo_db = MagicMock()
            mock_mongo_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_get_mongo.return_value = mock_mongo_db

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

    def test_alerts_no_run_exists(self, client_with_auth):
        """GET alerts with no run should return 404."""
        with patch("app.routes.liquidity_risk.get_mongo_db") as mock_get_mongo:
            mock_collection = AsyncMock()
            mock_collection.find_one = AsyncMock(return_value=None)
            mock_mongo_db = MagicMock()
            mock_mongo_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_get_mongo.return_value = mock_mongo_db

            response = client_with_auth.get("/api/liquidity-risk/alerts")

            assert response.status_code == 404
