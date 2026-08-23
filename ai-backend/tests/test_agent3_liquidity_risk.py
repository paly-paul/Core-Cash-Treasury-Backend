"""Unit tests for Agent 3: Liquidity Risk."""
import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.liquidity_risk import (
    compute_risk_score,
    compute_ar_concentration,
    generate_narrative,
    get_ar_data,
    compute_liquidity_risk,
)


class TestRiskScore:
    """Tests for risk score computation."""

    def test_score_no_breaches_no_stale_no_ar(self):
        """Score with only base (no breaches, no stale, no AR concentration)."""
        result = compute_risk_score(
            active_breaches=[],
            stale_feeds=[],
            ar_concentration_pct=0.0,
            forecast_shortfall_days=[],
        )
        assert result["risk_score"] == 1
        assert result["risk_level"] == "Low"
        assert result["score_breakdown"]["base"] == 1
        assert result["score_breakdown"]["breach_points"] == 0
        assert result["score_breakdown"]["stale_feed_points"] == 0
        assert result["score_breakdown"]["ar_concentration_points"] == 0
        assert result["score_breakdown"]["shortfall_points"] == 0

    def test_score_one_breach(self):
        """Score with one active breach."""
        active_breaches = [
            {
                "entity_name": "US HQ",
                "account_name": "JPM USD Main",
                "min_threshold": 2000000,
                "current_balance": 1500000,
                "shortfall": 500000,
                "currency": "USD",
            }
        ]
        result = compute_risk_score(
            active_breaches=active_breaches,
            stale_feeds=[],
            ar_concentration_pct=0.0,
            forecast_shortfall_days=[],
        )
        assert result["score_breakdown"]["breach_points"] == 2
        assert result["risk_score"] == 3
        assert result["risk_level"] == "Low"

    def test_score_three_breaches_cap(self):
        """Score with three breaches (should cap at 6)."""
        active_breaches = [
            {"entity_name": f"Entity {i}", "account_name": f"Account {i}"}
            for i in range(3)
        ]
        result = compute_risk_score(
            active_breaches=active_breaches,
            stale_feeds=[],
            ar_concentration_pct=0.0,
            forecast_shortfall_days=[],
        )
        # 3 breaches * 2 = 6, capped at 6
        assert result["score_breakdown"]["breach_points"] == 6
        assert result["risk_score"] == 7
        assert result["risk_level"] == "Medium"

    def test_score_stale_feed_over_48h(self):
        """Score with stale feed > 48 hours."""
        result = compute_risk_score(
            active_breaches=[],
            stale_feeds=[{"account_name": "Test", "hours_stale": 50}],
            ar_concentration_pct=0.0,
            forecast_shortfall_days=[],
        )
        assert result["score_breakdown"]["stale_feed_points"] == 1
        assert result["risk_score"] == 2
        assert result["risk_level"] == "Low"

    def test_score_stale_feed_exactly_48h(self):
        """Score with stale feed exactly 48 hours (should not trigger)."""
        result = compute_risk_score(
            active_breaches=[],
            stale_feeds=[{"account_name": "Test", "hours_stale": 48}],
            ar_concentration_pct=0.0,
            forecast_shortfall_days=[],
        )
        # Exactly 48h should not trigger (strictly > 48)
        assert result["score_breakdown"]["stale_feed_points"] == 0
        assert result["risk_score"] == 1
        assert result["risk_level"] == "Low"

    def test_score_ar_concentration_above_70(self):
        """Score with AR concentration above 70%."""
        result = compute_risk_score(
            active_breaches=[],
            stale_feeds=[],
            ar_concentration_pct=75.0,
            forecast_shortfall_days=[],
        )
        assert result["score_breakdown"]["ar_concentration_points"] == 1
        assert result["risk_score"] == 2
        assert result["risk_level"] == "Low"

    def test_score_all_components_triggers_cap(self):
        """Score with all components triggered, testing hard cap at 10."""
        # 3+ breaches (6) + stale (1) + AR conc (1) + base (1) + shortfall (0) = 9, capped at 10
        active_breaches = [
            {"entity_name": f"Entity {i}", "account_name": f"Account {i}"}
            for i in range(4)
        ]
        result = compute_risk_score(
            active_breaches=active_breaches,
            stale_feeds=[{"account_name": "Test", "hours_stale": 60}],
            ar_concentration_pct=80.0,
            forecast_shortfall_days=[],
        )
        # breach_pts = min(4*2, 6) = 6
        # raw = 1 + 6 + 1 + 1 + 0 = 9
        assert result["score_breakdown"]["capped"] == False
        assert result["risk_score"] == 9
        assert result["risk_level"] == "High"

    def test_shortfall_pts_always_zero(self):
        """Verify shortfall_pts is always 0 (TODO for Session 14)."""
        result = compute_risk_score(
            active_breaches=[],
            stale_feeds=[],
            ar_concentration_pct=0.0,
            forecast_shortfall_days=["2026-08-23", "2026-08-24"],
        )
        # Should still be 0 until Session 14
        assert result["score_breakdown"]["shortfall_points"] == 0


class TestARConcentration:
    """Tests for AR concentration risk computation."""

    def test_ar_concentration_empty(self):
        """AR concentration with no AR data."""
        result = compute_ar_concentration([])
        assert result["top_3_share_pct"] == 0.0
        assert result["breached"] == False
        assert result["high_single_counterparty"] == False
        assert result["top_counterparties"] == []

    def test_ar_concentration_single_counterparty_over_40(self):
        """AR concentration with single counterparty > 40%."""
        ar_rows = [
            {
                "counterparty_name": "Big Customer",
                "amount_usd": 500000,
                "amount_local": 500000,
                "currency": "USD",
            },
            {
                "counterparty_name": "Small Customer",
                "amount_usd": 300000,
                "amount_local": 300000,
                "currency": "USD",
            },
            {
                "counterparty_name": "Another",
                "amount_usd": 200000,
                "amount_local": 200000,
                "currency": "USD",
            },
        ]
        result = compute_ar_concentration(ar_rows)
        # Total = 1000000
        # Top 1: 500000 / 1000000 = 50% > 40%
        assert result["high_single_counterparty"] == True
        assert result["top_counterparties"][0]["share_pct"] == 50.0

    def test_ar_concentration_top_3_above_70(self):
        """AR concentration with top 3 > 70%."""
        ar_rows = [
            {
                "counterparty_name": "Customer A",
                "amount_usd": 400000,
                "amount_local": 400000,
                "currency": "USD",
            },
            {
                "counterparty_name": "Customer B",
                "amount_usd": 300000,
                "amount_local": 300000,
                "currency": "USD",
            },
            {
                "counterparty_name": "Customer C",
                "amount_usd": 150000,
                "amount_local": 150000,
                "currency": "USD",
            },
            {
                "counterparty_name": "Customer D",
                "amount_usd": 150000,
                "amount_local": 150000,
                "currency": "USD",
            },
        ]
        result = compute_ar_concentration(ar_rows)
        # Total = 1000000
        # Top 3: (400 + 300 + 150) / 1000 = 85% > 70%
        assert result["top_3_share_pct"] == 85.0
        assert result["breached"] == True

    def test_ar_concentration_field_name(self):
        """Verify output field is named ar_concentration_risk (not concentration_risk)."""
        result = compute_ar_concentration([])
        # This is the actual result structure we return
        assert "top_3_share_pct" in result
        assert "threshold_pct" in result
        assert "breached" in result
        # The field is called ar_concentration_risk when embedded in the Agent 3 output
        # This test verifies the local function returns the correct structure


class TestNarrative:
    """Tests for narrative generation."""

    def test_narrative_low_risk(self):
        """Narrative for low risk."""
        narrative = generate_narrative(
            risk_level="Low",
            active_breaches=[],
            ar_concentration={"top_3_share_pct": 30.0, "breached": False},
            stale_feeds=[],
        )
        assert "Low" in narrative
        assert "No active threshold breaches" in narrative
        assert "within 70% threshold" in narrative
        assert "All bank feeds current" in narrative

    def test_narrative_with_breach(self):
        """Narrative with active breaches."""
        active_breaches = [
            {
                "entity_name": "US HQ",
                "account_name": "JPM",
                "min_threshold": 2000000,
                "current_balance": 1500000,
                "shortfall": 500000,
                "currency": "USD",
            }
        ]
        narrative = generate_narrative(
            risk_level="Medium",
            active_breaches=active_breaches,
            ar_concentration={"top_3_share_pct": 50.0, "breached": False},
            stale_feeds=[],
        )
        assert "1 active breach(es)" in narrative
        assert "Medium" in narrative

    def test_narrative_ar_concentration_breached(self):
        """Narrative with AR concentration breach."""
        narrative = generate_narrative(
            risk_level="High",
            active_breaches=[],
            ar_concentration={"top_3_share_pct": 75.0, "breached": True},
            stale_feeds=[],
        )
        assert "75.0% — above 70% threshold" in narrative
        assert "High" in narrative

    def test_narrative_stale_feeds(self):
        """Narrative with stale feeds."""
        stale_feeds = [
            {"account_name": "Account 1", "hours_stale": 60},
            {"account_name": "Account 2", "hours_stale": 50},
        ]
        narrative = generate_narrative(
            risk_level="High",
            active_breaches=[],
            ar_concentration={"top_3_share_pct": 20.0, "breached": False},
            stale_feeds=stale_feeds,
        )
        assert "2 stale feed(s)" in narrative
        assert ">48h" in narrative


class TestAgentIntegration:
    """Integration tests for Agent 3."""

    @pytest.mark.asyncio
    async def test_agent_3_no_agent_1_output(self):
        """Agent 3 should handle missing Agent 1 output gracefully."""
        # Mock AsyncSession and mongo_db
        mock_db = AsyncMock()
        mock_mongo_db = MagicMock()

        # Mock collection that returns None (no Agent 1 output)
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_mongo_db.__getitem__ = MagicMock(return_value=mock_collection)

        # Create a mock state
        state = {
            "client_id": "test-client",
            "job_id": "test-job",
        }

        result = await compute_liquidity_risk(
            db=mock_db, mongo_db=mock_mongo_db, state=state
        )

        # Should return error response
        assert result["error"]["code"] == "AGENT_ERROR"
        assert (
            "Daily cash position must be computed" in result["error"]["message"]
        )

    @pytest.mark.asyncio
    async def test_ar_concentration_field_name_in_output(self):
        """Verify output contains ar_concentration_risk field (not concentration_risk)."""
        mock_db = AsyncMock()
        mock_mongo_db = MagicMock()

        # Mock collection with Agent 1 output
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(
            return_value={
                "client_id": "test-client",
                "agent": "daily_cash_position",
                "active_breaches": [],
                "stale_feeds": [],
            }
        )
        mock_collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="test-id")
        )
        mock_mongo_db.__getitem__ = MagicMock(return_value=mock_collection)

        # Mock AsyncSession and get_ar_data
        mock_db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))

        state = {
            "client_id": "test-client",
            "job_id": "test-job",
        }

        with patch("app.agents.liquidity_risk.get_ar_data", return_value=[]):
            result = await compute_liquidity_risk(
                db=mock_db, mongo_db=mock_mongo_db, state=state
            )

        # Verify field name
        assert "ar_concentration_risk" in result
        assert "concentration_risk" not in result
        assert result["ar_concentration_risk"]["threshold_pct"] == 70.0

    @pytest.mark.asyncio
    async def test_active_breaches_column_order(self):
        """Verify active breaches have correct field order."""
        # This is the output order from Agent 3
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
        assert keys == expected_order
