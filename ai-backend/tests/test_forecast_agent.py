"""
Tests for Forecast Agent (Agent 2).

Tests cover:
1. Blocked path (no bank statement data)
2. Partial path (opening balance found, assumptions exist)
3. Running balance continuity
4. Confidence band calculation
5. Shortfall signal detection
6. Assumptions threshold filtering
"""

import pytest
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.agents.forecast import ForecastAgent, AgentState


@pytest.fixture
def mock_db():
    """Mock AsyncSession for PostgreSQL."""
    return AsyncMock()


@pytest.fixture
def mock_mongo():
    """Mock MongoDB client."""
    mongo = MagicMock()
    mongo.forecast_runs = AsyncMock()
    mongo.agent_2_signals = AsyncMock()
    return mongo


@pytest.fixture
def client_id():
    return str(uuid4())


@pytest.fixture
def entity_id():
    return str(uuid4())


class TestForecastAgentBlockedPath:
    """Test forecast agent when opening balance is unavailable (BLOCKED)."""

    @pytest.mark.asyncio
    async def test_blocked_no_bank_statement(self, mock_db, mock_mongo, client_id, entity_id):
        """
        Test 1: Forecast blocked when no bank statement data found.

        Assert:
        - MongoDB document written with data_status="blocked"
        - blocked_reason contains "OPENING_BALANCE_UNRESOLVED"
        - forecast_rows == []
        - state["errors"]["agent_2"] is set
        """
        # Mock: no assumptions
        mock_db.execute.return_value.fetchall.return_value = []

        # Mock: no opening balance found
        mock_db.execute.return_value.fetchone.return_value = None

        # Mock: entity name query
        async def mock_execute_side_effect(*args, **kwargs):
            result = AsyncMock()
            if "legal_entity" in str(args):
                result.fetchone.return_value = MagicMock(name="Test Entity")
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute_side_effect)

        agent = ForecastAgent(db=mock_db, mongo=mock_mongo)
        state = AgentState(
            client_id=client_id,
            entity_id=entity_id,
            job_id="job_123",
            errors={},
        )

        await agent.run(state)

        # Assertions
        assert state.data_status == "blocked"
        assert "agent_2" in state.errors
        assert "OPENING_BALANCE_UNRESOLVED" in state.errors["agent_2"]

        # Verify MongoDB document was written
        mock_mongo.forecast_runs.insert_one.assert_called_once()
        doc = mock_mongo.forecast_runs.insert_one.call_args[0][0]
        assert doc["data_status"] == "blocked"
        assert doc["blocked_reason"] is not None
        assert doc["forecast_rows"] == []
        assert doc["opening_balance_usd"] is None


class TestForecastAgentPartialPath:
    """Test forecast agent when opening balance is found (PARTIAL)."""

    @pytest.mark.asyncio
    async def test_partial_with_assumptions(self, mock_db, mock_mongo, client_id, entity_id):
        """
        Test 2: Partial forecast when opening balance found and assumptions exist.

        Assert:
        - data_status == "partial"
        - len(forecast_rows) == 30
        - assumptions_used == 3, assumptions_skipped == 1
        - forecast_rows[0].opening_balance_usd == 5_000_000
        """
        opening_balance = 5_000_000.0

        # Mock assumptions: 3 included (confidence >= 50), 1 skipped
        assumptions = [
            MagicMock(
                id=1,
                entity_id=entity_id,
                amount_usd=100_000,
                date=date(2026, 8, 25),
                category="AR_COLLECTION",
                confidence_pct=75,
            ),
            MagicMock(
                id=2,
                entity_id=entity_id,
                amount_usd=50_000,
                date=date(2026, 8, 26),
                category="AP_PAYMENT",
                confidence_pct=60,
            ),
            MagicMock(
                id=3,
                entity_id=entity_id,
                amount_usd=200_000,
                date=date(2026, 8, 27),
                category="OTHER_OUTFLOW",
                confidence_pct=55,
            ),
            MagicMock(
                id=4,
                entity_id=entity_id,
                amount_usd=75_000,
                date=date(2026, 8, 28),
                category="PAYROLL",
                confidence_pct=30,  # SKIPPED
            ),
        ]

        async def mock_execute_side_effect(*args, **kwargs):
            result = AsyncMock()
            if "manual_assumptions" in str(args):
                result.fetchall.return_value = assumptions
            elif "bank_statement" in str(args):
                result.fetchone.return_value = MagicMock(balance_after=opening_balance)
            elif "legal_entity" in str(args):
                result.fetchone.return_value = MagicMock(name="Test Entity")
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute_side_effect)

        agent = ForecastAgent(db=mock_db, mongo=mock_mongo)
        state = AgentState(
            client_id=client_id,
            entity_id=entity_id,
            job_id="job_123",
            errors={},
        )

        await agent.run(state)

        # Assertions
        assert state.data_status == "partial"
        mock_mongo.forecast_runs.insert_one.assert_called_once()
        doc = mock_mongo.forecast_runs.insert_one.call_args[0][0]
        assert doc["data_status"] == "partial"
        assert len(doc["forecast_rows"]) == 30
        assert doc["assumptions_used"] == 3
        assert doc["assumptions_skipped"] == 1
        assert doc["forecast_rows"][0]["opening_balance_usd"] == opening_balance


class TestForecastRunningBalance:
    """Test continuity of opening/closing balance across days."""

    @pytest.mark.asyncio
    async def test_running_balance_continuity(self, mock_db, mock_mongo, client_id, entity_id):
        """
        Test 3: Running balance carries forward correctly.

        Setup: Opening = 1_000_000; day 1 inflow = 200_000, outflow = 150_000
        Assert:
        - forecast_rows[0].projected_closing_usd == 1_050_000
        - forecast_rows[1].opening_balance_usd == 1_050_000
        """
        opening_balance = 1_000_000.0

        # Single assumption on day 1
        assumptions = [
            MagicMock(
                id=1,
                entity_id=entity_id,
                amount_usd=200_000,
                date=date(2026, 8, 25),
                category="AR_COLLECTION",
                confidence_pct=75,
            ),
            MagicMock(
                id=2,
                entity_id=entity_id,
                amount_usd=150_000,
                date=date(2026, 8, 25),
                category="AP_PAYMENT",
                confidence_pct=75,
            ),
        ]

        async def mock_execute_side_effect(*args, **kwargs):
            result = AsyncMock()
            if "manual_assumptions" in str(args):
                result.fetchall.return_value = assumptions
            elif "bank_statement" in str(args):
                result.fetchone.return_value = MagicMock(balance_after=opening_balance)
            elif "legal_entity" in str(args):
                result.fetchone.return_value = MagicMock(name="Test Entity")
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute_side_effect)

        agent = ForecastAgent(db=mock_db, mongo=mock_mongo)
        state = AgentState(
            client_id=client_id,
            entity_id=entity_id,
            job_id="job_123",
            errors={},
        )

        await agent.run(state)

        doc = mock_mongo.forecast_runs.insert_one.call_args[0][0]
        rows = doc["forecast_rows"]

        # Day 1: 1M + 200k inflow - 150k outflow = 1.05M
        assert rows[0]["projected_closing_usd"] == 1_050_000

        # Day 2: should open with day 1's closing
        assert rows[1]["opening_balance_usd"] == 1_050_000


class TestConfidenceBands:
    """Test confidence band calculation (±15% placeholder)."""

    @pytest.mark.asyncio
    async def test_confidence_band_calculation(self, mock_db, mock_mongo, client_id, entity_id):
        """
        Test 4: Confidence bands are ±15% of projected closing.

        Setup: projected_closing = 1_000_000
        Assert:
        - confidence_band_low == 850_000 (1M - 15%)
        - confidence_band_high == 1_150_000 (1M + 15%)
        """
        opening_balance = 1_000_000.0

        # No assumptions = zero inflow/outflow, so closing = opening
        async def mock_execute_side_effect(*args, **kwargs):
            result = AsyncMock()
            if "manual_assumptions" in str(args):
                result.fetchall.return_value = []
            elif "bank_statement" in str(args):
                result.fetchone.return_value = MagicMock(balance_after=opening_balance)
            elif "legal_entity" in str(args):
                result.fetchone.return_value = MagicMock(name="Test Entity")
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute_side_effect)

        agent = ForecastAgent(db=mock_db, mongo=mock_mongo)
        state = AgentState(
            client_id=client_id,
            entity_id=entity_id,
            job_id="job_123",
            errors={},
        )

        await agent.run(state)

        doc = mock_mongo.forecast_runs.insert_one.call_args[0][0]
        rows = doc["forecast_rows"]

        row = rows[0]
        assert row["projected_closing_usd"] == opening_balance
        assert row["confidence_band_low_usd"] == 850_000  # 1M * (1 - 0.15)
        assert row["confidence_band_high_usd"] == 1_150_000  # 1M * (1 + 0.15)


class TestShortfallSignal:
    """Test shortfall detection and signal writing."""

    @pytest.mark.asyncio
    async def test_shortfall_signal_written_when_negative(self, mock_db, mock_mongo, client_id, entity_id):
        """
        Test 5: Shortfall signal written when closing goes negative.

        Setup: Opening = 100_000; outflow day 1 = 200_000 (closing = -100_000)
        Assert:
        - agent_2_signals collection written with shortfall_detected=True
        - shortfall_day == 1
        - shortfall_amount_usd == 100_000
        """
        opening_balance = 100_000.0

        # Heavy outflow on day 1
        assumptions = [
            MagicMock(
                id=1,
                entity_id=entity_id,
                amount_usd=200_000,
                date=date(2026, 8, 25),
                category="AP_PAYMENT",
                confidence_pct=75,
            ),
        ]

        async def mock_execute_side_effect(*args, **kwargs):
            result = AsyncMock()
            if "manual_assumptions" in str(args):
                result.fetchall.return_value = assumptions
            elif "bank_statement" in str(args):
                result.fetchone.return_value = MagicMock(balance_after=opening_balance)
            elif "legal_entity" in str(args):
                result.fetchone.return_value = MagicMock(name="Test Entity")
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute_side_effect)

        agent = ForecastAgent(db=mock_db, mongo=mock_mongo)
        state = AgentState(
            client_id=client_id,
            entity_id=entity_id,
            job_id="job_123",
            errors={},
        )

        await agent.run(state)

        # Verify shortfall signal written
        mock_mongo.agent_2_signals.insert_one.assert_called_once()
        signal = mock_mongo.agent_2_signals.insert_one.call_args[0][0]
        assert signal["shortfall_detected"] is True
        assert signal["shortfall_day"] == 1
        assert signal["shortfall_amount_usd"] == 100_000


class TestAssumptionFiltering:
    """Test assumption confidence threshold filtering."""

    @pytest.mark.asyncio
    async def test_assumptions_below_threshold_excluded(self, mock_db, mock_mongo, client_id, entity_id):
        """
        Test 6: All assumptions below confidence threshold are excluded.

        Setup: 3 assumptions all with confidence_pct = 40 (all below threshold of 50)
        Assert:
        - assumptions_used == 0
        - assumptions_skipped == 3
        - forecast_rows have assumptions_applied == []
        """
        opening_balance = 1_000_000.0

        # All below threshold
        assumptions = [
            MagicMock(
                id=1,
                entity_id=entity_id,
                amount_usd=100_000,
                date=date(2026, 8, 25),
                category="AR_COLLECTION",
                confidence_pct=40,
            ),
            MagicMock(
                id=2,
                entity_id=entity_id,
                amount_usd=50_000,
                date=date(2026, 8, 26),
                category="AP_PAYMENT",
                confidence_pct=40,
            ),
            MagicMock(
                id=3,
                entity_id=entity_id,
                amount_usd=75_000,
                date=date(2026, 8, 27),
                category="PAYROLL",
                confidence_pct=40,
            ),
        ]

        async def mock_execute_side_effect(*args, **kwargs):
            result = AsyncMock()
            if "manual_assumptions" in str(args):
                result.fetchall.return_value = assumptions
            elif "bank_statement" in str(args):
                result.fetchone.return_value = MagicMock(balance_after=opening_balance)
            elif "legal_entity" in str(args):
                result.fetchone.return_value = MagicMock(name="Test Entity")
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute_side_effect)

        agent = ForecastAgent(db=mock_db, mongo=mock_mongo)
        state = AgentState(
            client_id=client_id,
            entity_id=entity_id,
            job_id="job_123",
            errors={},
        )

        await agent.run(state)

        doc = mock_mongo.forecast_runs.insert_one.call_args[0][0]
        rows = doc["forecast_rows"]

        assert doc["assumptions_used"] == 0
        assert doc["assumptions_skipped"] == 3

        # All rows should have empty assumptions_applied
        for row in rows:
            assert row["assumptions_applied"] == []
