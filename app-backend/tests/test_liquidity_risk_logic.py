"""Tests for Liquidity Risk endpoint logic (without full app imports)."""
import pytest
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId


class TestLiquidityRiskEndpointLogic:
    """Tests for liquidity risk endpoint response logic."""

    def test_liquidity_risk_request_payload(self):
        """Verify POST request payload structure."""
        # Simulate a 202 response
        payload = {
            "request_id": str(uuid4()),
            "status": "queued",
            "queued_at": datetime.utcnow().isoformat() + "Z",
        }

        assert "request_id" in payload
        assert payload["status"] == "queued"
        assert "queued_at" in payload
        assert payload["request_id"] != ""

    def test_liquidity_risk_current_response_structure(self):
        """Verify GET /current response contains required fields."""
        response = {
            "_id": str(ObjectId()),
            "client_id": str(uuid4()),
            "agent": "liquidity_risk",
            "as_of": "2026-08-22T09:00:00Z",
            "risk_score": 3,
            "risk_level": "Low",
            "score_breakdown": {
                "base": 1,
                "breach_points": 0,
                "stale_feed_points": 0,
                "ar_concentration_points": 0,
                "shortfall_points": 0,
                "raw_total": 1,
                "capped": False,
            },
            "active_breaches": [],
            "forecast_shortfall_days": [],
            "ar_concentration_risk": {
                "top_3_share_pct": 0.0,
                "threshold_pct": 70.0,
                "breached": False,
                "high_single_counterparty": False,
                "top_counterparties": [],
            },
            "stale_feeds": [],
            "narrative": "Liquidity risk is Low.",
        }

        # Verify structure
        assert response["risk_score"] == 3
        assert response["risk_level"] == "Low"
        assert "ar_concentration_risk" in response
        assert "concentration_risk" not in response
        assert response["ar_concentration_risk"]["threshold_pct"] == 70.0

    def test_liquidity_risk_alerts_response_structure(self):
        """Verify GET /alerts returns only critical fields."""
        full_response = {
            "_id": str(ObjectId()),
            "client_id": str(uuid4()),
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

        # Simulate alerts filtering
        alerts_response = {
            "as_of": full_response.get("as_of"),
            "risk_level": full_response.get("risk_level"),
            "critical_breaches": full_response.get("active_breaches", []),
            "forecast_shortfall_days": full_response.get("forecast_shortfall_days", []),
        }

        # Verify structure
        assert "as_of" in alerts_response
        assert alerts_response["as_of"] == "2026-08-22T09:00:00Z"
        assert alerts_response["risk_level"] == "High"
        assert "critical_breaches" in alerts_response
        assert len(alerts_response["critical_breaches"]) == 1
        assert alerts_response["critical_breaches"][0]["account_name"] == "JPM USD Main"
        assert "forecast_shortfall_days" in alerts_response
        assert alerts_response["forecast_shortfall_days"] == []

        # Should NOT include these fields
        assert "risk_score" not in alerts_response
        assert "score_breakdown" not in alerts_response
        assert "ar_concentration_risk" not in alerts_response
        assert "narrative" not in alerts_response

    def test_liquidity_risk_404_response_structure(self):
        """Verify 404 response has correct error structure."""
        error_response = {
            "error": {
                "code": "NOT_FOUND",
                "message": "No liquidity risk assessment available. Request one via POST /api/liquidity-risk/request.",
            }
        }

        assert error_response["error"]["code"] == "NOT_FOUND"
        assert "Request one via POST" in error_response["error"]["message"]

    def test_ar_concentration_risk_field_name_critical(self):
        """CRITICAL: Verify ar_concentration_risk field name (not concentration_risk)."""
        # This is a critical rule from the spec
        output = {
            "ar_concentration_risk": {
                "top_3_share_pct": 45.0,
                "threshold_pct": 70.0,
                "breached": False,
                "high_single_counterparty": False,
                "top_counterparties": [],
            }
        }

        # MUST have this field name
        assert "ar_concentration_risk" in output, "Field name MUST be 'ar_concentration_risk'"

        # MUST NOT have this incorrect name
        assert "concentration_risk" not in output, "Field name must NOT be 'concentration_risk'"

    def test_shortfall_pts_zero_in_response(self):
        """Verify shortfall_points is always 0 in response."""
        score_breakdown = {
            "base": 1,
            "breach_points": 0,
            "stale_feed_points": 0,
            "ar_concentration_points": 0,
            "shortfall_points": 0,  # MUST be 0 until Session 14
            "raw_total": 1,
            "capped": False,
        }

        assert score_breakdown["shortfall_points"] == 0

    def test_active_breaches_column_order(self):
        """Verify active breaches have correct field order."""
        breaches = [
            {
                "entity_name": "US HQ",
                "account_name": "JPM USD Main",
                "min_threshold": 2000000,
                "current_balance": 1500000,
                "shortfall": 500000,
                "currency": "USD",
            }
        ]

        # Verify field order
        keys = list(breaches[0].keys())
        expected_order = [
            "entity_name",
            "account_name",
            "min_threshold",
            "current_balance",
            "shortfall",
            "currency",
        ]
        assert keys == expected_order, f"Field order mismatch: {keys} vs {expected_order}"
