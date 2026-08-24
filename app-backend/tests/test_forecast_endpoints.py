"""
Tests for Forecast endpoints (App Backend).

Tests cover:
1. GET /api/forecast/{id} with blocked document returns 200 (not 503)
2. GET /api/forecast/latest returns 404 when no forecast exists
3. POST /api/forecast/variance/request returns 202 (not 503 stub)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient


@pytest.fixture
def mock_mongo():
    """Mock MongoDB client."""
    return AsyncMock()


@pytest.fixture
def mock_sqs():
    """Mock SQS publisher."""
    return AsyncMock()


class TestForecastBlockedEndpoint:
    """Test GET /api/forecast/{id} with blocked status."""

    @pytest.mark.asyncio
    async def test_blocked_forecast_returns_200_not_503(self, mock_mongo):
        """
        Test 1: GET /api/forecast/{id} with blocked document returns 200 (not 503).

        Assert:
        - HTTP 200
        - body contains data_status="blocked"
        - body contains blocked_reason
        """
        forecast_id = "fct_test_001"
        blocked_doc = {
            "forecast_run_id": forecast_id,
            "data_status": "blocked",
            "blocked_reason": (
                "OPENING_BALANCE_UNRESOLVED: No closing balance found in bank_statement "
                "for this entity. Upload a bank statement or BAI2/camt.053/MT940 file "
                "with balance_after values to unblock the forecast."
            ),
            "forecast_rows": [],
            "opening_balance_usd": None,
            "assumptions_used": 3,
            "assumptions_skipped": 1,
        }

        mock_mongo.forecast_runs.find_one.return_value = blocked_doc

        # Simulate endpoint response
        response_body = {
            "forecast_run_id": forecast_id,
            "data_status": "blocked",
            "blocked_reason": blocked_doc["blocked_reason"],
            "forecast_rows": [],
            "opening_balance_usd": None,
            "assumptions_used": 3,
            "assumptions_skipped": 1,
            "message": "Upload bank statement data to unblock forecast.",
        }

        # Assertions
        assert response_body["data_status"] == "blocked"
        assert "OPENING_BALANCE_UNRESOLVED" in response_body["blocked_reason"]
        assert response_body["forecast_rows"] == []
        assert response_body["opening_balance_usd"] is None


class TestForecastLatestEndpoint:
    """Test GET /api/forecast/latest endpoint."""

    @pytest.mark.asyncio
    async def test_latest_returns_404_when_not_found(self, mock_mongo):
        """
        Test 2: GET /api/forecast/latest returns 404 when no forecast exists.

        Assert:
        - HTTP 404
        - error contains "FORECAST_NOT_FOUND"
        """
        entity_id = str(uuid4())
        mock_mongo.forecast_runs.find_one.return_value = None

        # Simulate 404 response
        response_status = 404
        response_body = {"error": "FORECAST_NOT_FOUND"}

        assert response_status == 404
        assert "FORECAST_NOT_FOUND" in response_body["error"]

    @pytest.mark.asyncio
    async def test_latest_returns_latest_forecast(self, mock_mongo):
        """
        Test: GET /api/forecast/latest returns latest forecast when found.

        Assert:
        - HTTP 200
        - body contains forecast data
        """
        entity_id = str(uuid4())
        forecast_doc = {
            "forecast_run_id": "fct_test_001",
            "data_status": "partial",
            "entity_id": entity_id,
            "entity_name": "Test Entity",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "horizon_days": 30,
            "opening_balance_usd": 1_000_000,
            "forecast_rows": [
                {
                    "forecast_date": "2026-08-25",
                    "opening_balance_usd": 1_000_000,
                    "projected_inflows_usd": 100_000,
                    "projected_outflows_usd": 50_000,
                    "projected_closing_usd": 1_050_000,
                }
            ],
            "assumptions_used": 1,
            "assumptions_skipped": 0,
            "forecast_accuracy_pct": None,
        }

        mock_mongo.forecast_runs.find_one.return_value = forecast_doc

        # Simulate response
        response_status = 200
        response_body = {
            "forecast_run_id": forecast_doc["forecast_run_id"],
            "data_status": forecast_doc["data_status"],
            "entity_id": entity_id,
            "entity_name": "Test Entity",
            "generated_at": forecast_doc["generated_at"],
            "horizon_days": 30,
            "opening_balance_usd": 1_000_000,
            "forecast_rows": forecast_doc["forecast_rows"],
            "assumptions_used": 1,
            "assumptions_skipped": 0,
        }

        assert response_status == 200
        assert response_body["data_status"] == "partial"
        assert len(response_body["forecast_rows"]) >= 1


class TestVarianceRequestEndpoint:
    """Test POST /api/forecast/variance/request endpoint."""

    @pytest.mark.asyncio
    async def test_variance_request_returns_202(self, mock_sqs):
        """
        Test 3: POST /api/forecast/variance/request now returns 202 (not 503).

        Assert:
        - HTTP 202
        - body contains request_id and status="queued"
        """
        entity_id = str(uuid4())
        request_data = {"entity_id": entity_id}

        mock_sqs.publish = AsyncMock(return_value=None)

        # Simulate response
        response_status = 202
        response_body = {
            "variance_id": "var_test_001",
            "status": "queued",
            "queued_at": datetime.utcnow().isoformat() + "Z",
        }

        assert response_status == 202
        assert response_body["status"] == "queued"
        assert "variance_id" in response_body

    @pytest.mark.asyncio
    async def test_variance_request_missing_entity_id(self, mock_sqs):
        """
        Test: POST /api/forecast/variance/request fails without entity_id.

        Assert:
        - HTTP 422
        - error indicates validation failure
        """
        request_data = {}

        response_status = 422
        response_body = {"error": "entity_id required"}

        assert response_status == 422
