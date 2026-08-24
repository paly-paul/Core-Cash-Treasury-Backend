"""
Agent 2: Forecast Intelligence (structurally complete, calculation blocked pending real data).

BLOCKED PATH: Returns completed MongoDB document with data_status="blocked"
and OPENING_BALANCE_UNRESOLVED error when bank_statement data unavailable.

PARTIAL PATH: Returns forecast with manual assumptions when opening balance found.
AP/AR actuals not yet wired (post-MVP).
"""

from datetime import datetime, timedelta, date as DateType
from typing import Optional
from uuid import uuid4
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

from core_cash_shared.schemas.forecast import ForecastResult, ForecastDayRow

logger = logging.getLogger(__name__)


class AgentState:
    """Shared state across agent run."""
    def __init__(self, client_id: str, entity_id: str, job_id: str, errors: dict = None):
        self.client_id = client_id
        self.entity_id = entity_id
        self.job_id = job_id
        self.errors = errors or {}
        self.forecast_run_id: Optional[str] = None
        self.data_status: Optional[str] = None


class ForecastAgent:
    """
    Forecast Intelligence Agent.

    Execution flow:
    1. Load manual assumptions from PostgreSQL (confidence >= 50%)
    2. Resolve opening balance from bank_statement (BLOCKED if not found)
    3. Build 30-day forecast rows (runs only if opening_balance_usd resolved)
    4. Write to MongoDB forecast_runs collection
    5. Signal shortfall detection to agent_2_signals collection
    """

    def __init__(self, db: AsyncSession, mongo: AsyncIOMotorDatabase):
        self.db = db
        self.mongo = mongo
        self.confidence_threshold = 50

    async def run(self, state: AgentState) -> None:
        """Execute the forecast agent pipeline."""
        try:
            # STEP 1: Load and filter manual assumptions
            included_assumptions, skipped_assumptions = await self._load_assumptions(
                state.client_id, state.entity_id
            )

            # STEP 2: Resolve opening balance from bank_statement
            opening_balance_usd = await self._resolve_opening_balance(
                state.client_id, state.entity_id
            )

            # STEP 3: Determine data_status and blocked_reason
            if opening_balance_usd is None:
                data_status = "blocked"
                blocked_reason = (
                    "OPENING_BALANCE_UNRESOLVED: No closing balance found in bank_statement "
                    "for this entity. Upload a bank statement or BAI2/camt.053/MT940 file "
                    "with balance_after values to unblock the forecast."
                )
                forecast_rows = []
            else:
                data_status = "partial"
                blocked_reason = None
                # STEP 3: Build forecast rows
                forecast_rows = await self._build_forecast_rows(
                    opening_balance_usd, included_assumptions
                )

            # STEP 4: Write to MongoDB
            forecast_run_id = str(uuid4())
            entity_name = await self._get_entity_name(state.client_id, state.entity_id)

            result_doc = {
                "forecast_run_id": forecast_run_id,
                "entity_id": state.entity_id,
                "entity_name": entity_name,
                "client_id": state.client_id,
                "job_id": state.job_id,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "horizon_days": 30,
                "data_status": data_status,
                "blocked_reason": blocked_reason,
                "opening_balance_usd": opening_balance_usd,
                "forecast_rows": [r.model_dump() for r in forecast_rows],
                "assumptions_used": len(included_assumptions),
                "assumptions_skipped": len(skipped_assumptions),
                "forecast_accuracy_pct": None,  # populated by Agent 5 after variance runs
                "notes": [
                    "Confidence bands: ±15% placeholder. ML model pending post-MVP.",
                    "AP/AR actuals not yet wired — only manual assumptions used.",
                    f"{len(skipped_assumptions)} assumption(s) excluded (confidence_pct < 50).",
                ],
            }

            await self.mongo.forecast_runs.insert_one(result_doc)
            state.forecast_run_id = forecast_run_id
            state.data_status = data_status

            if data_status == "blocked":
                state.errors["agent_2"] = blocked_reason
                logger.warning(f"Forecast blocked for entity {state.entity_id}: {blocked_reason}")

            # STEP 5: Write Agent 3 shortfall signal (if not blocked)
            if data_status != "blocked" and forecast_rows:
                await self._write_shortfall_signal(state, forecast_rows)

            logger.info(f"Forecast agent completed for {state.entity_id}: data_status={data_status}")

        except Exception as e:
            logger.error(f"Forecast agent failed: {e}", exc_info=True)
            state.errors["agent_2"] = str(e)
            raise

    async def _load_assumptions(self, client_id: str, entity_id: str) -> tuple[list, list]:
        """
        Load manual assumptions from PostgreSQL.

        Returns:
            (included_assumptions, skipped_assumptions) tuples
        """
        query = """
            SELECT
                id,
                entity_id,
                amount_usd,
                date,
                category,
                confidence_pct
            FROM manual_assumptions
            WHERE entity_id = :entity_id
              AND client_id = :client_id
              AND deleted_at IS NULL
              AND date >= CURRENT_DATE
            ORDER BY date ASC
        """

        result = await self.db.execute(text(query), {"entity_id": entity_id, "client_id": client_id})
        rows = result.fetchall()

        included = []
        skipped = []

        for row in rows:
            assumption = {
                "id": row.id,
                "entity_id": row.entity_id,
                "amount_usd": row.amount_usd,
                "date": row.date,
                "category": row.category,
                "confidence_pct": row.confidence_pct,
            }
            if row.confidence_pct >= self.confidence_threshold:
                included.append(assumption)
            else:
                skipped.append(assumption)

        logger.info(
            f"Loaded {len(included)} assumptions (included), {len(skipped)} skipped for {entity_id}"
        )
        return included, skipped

    async def _resolve_opening_balance(self, client_id: str, entity_id: str) -> Optional[float]:
        """
        Resolve opening balance from latest bank_statement closing balance.

        Returns:
            float if found, None if blocked
        """
        query = """
            SELECT balance_after
            FROM bank_statement
            WHERE entity_id = :entity_id
              AND client_id = :client_id
              AND balance_after IS NOT NULL
              AND include_in_cash_position = TRUE
            ORDER BY transaction_date DESC
            LIMIT 1
        """

        result = await self.db.execute(text(query), {"entity_id": entity_id, "client_id": client_id})
        row = result.fetchone()

        if row:
            opening_balance = float(row.balance_after)
            logger.info(f"Opening balance resolved for {entity_id}: {opening_balance}")
            return opening_balance
        else:
            logger.warning(f"Opening balance not found for entity {entity_id}")
            return None

    async def _build_forecast_rows(
        self, opening_balance_usd: float, included_assumptions: list
    ) -> list[ForecastDayRow]:
        """
        Build 30-day forecast rows using manual assumptions.

        TODO post-MVP: Replace with ML model (ARIMA/linear regression on 90-day history).
        AP/AR actuals from parsed uploads (Sessions 3 + 10) to feed distributions.
        """
        forecast_rows = []
        today = datetime.utcnow().date()

        for day_num in range(1, 31):  # 30-day horizon
            forecast_date = today + timedelta(days=day_num)

            # Collect assumptions for this date
            day_assumptions = [
                a for a in included_assumptions
                if a["date"] == forecast_date
            ]

            # Calculate inflows and outflows
            projected_inflows = sum(
                a["amount_usd"]
                for a in day_assumptions
                if a["category"] in ("AR_COLLECTION", "OTHER_INFLOW")
            )
            projected_outflows = sum(
                a["amount_usd"]
                for a in day_assumptions
                if a["category"] in ("AP_PAYMENT", "PAYROLL", "TAX", "CAPEX", "OTHER_OUTFLOW")
            )

            # Running balance
            if day_num == 1:
                day_opening = opening_balance_usd
            else:
                day_opening = forecast_rows[-1].projected_closing_usd

            projected_closing = day_opening + projected_inflows - projected_outflows

            # Confidence band: ±15% placeholder
            band_spread = abs(projected_closing) * 0.15
            confidence_band_low = projected_closing - band_spread
            confidence_band_high = projected_closing + band_spread

            forecast_rows.append(
                ForecastDayRow(
                    forecast_date=forecast_date,
                    opening_balance_usd=day_opening,
                    projected_inflows_usd=projected_inflows,
                    projected_outflows_usd=projected_outflows,
                    projected_closing_usd=projected_closing,
                    confidence_band_low_usd=confidence_band_low,
                    confidence_band_high_usd=confidence_band_high,
                    assumptions_applied=[str(a["id"]) for a in day_assumptions],
                )
            )

        return forecast_rows

    async def _get_entity_name(self, client_id: str, entity_id: str) -> str:
        """Retrieve entity name from legal_entity table."""
        query = "SELECT name FROM legal_entity WHERE id = :entity_id AND client_id = :client_id"
        result = await self.db.execute(text(query), {"entity_id": entity_id, "client_id": client_id})
        row = result.fetchone()
        return row.name if row else entity_id

    async def _write_shortfall_signal(self, state: AgentState, forecast_rows: list[ForecastDayRow]) -> None:
        """
        Write shortfall signal to agent_2_signals collection for Agent 3.

        Agent 3 reads this collection to populate shortfall_pts.
        """
        # Check for negative closing balances
        shortfall_day = None
        shortfall_amount_usd = 0

        for i, row in enumerate(forecast_rows):
            if row.projected_closing_usd is not None and row.projected_closing_usd < 0:
                shortfall_day = i + 1
                shortfall_amount_usd = abs(row.projected_closing_usd)
                break

        if shortfall_day is not None:
            signal_doc = {
                "entity_id": state.entity_id,
                "client_id": state.client_id,
                "job_id": state.job_id,
                "shortfall_detected": True,
                "shortfall_day": shortfall_day,
                "shortfall_amount_usd": shortfall_amount_usd,
                "computed_at": datetime.utcnow().isoformat() + "Z",
            }
            await self.mongo.agent_2_signals.insert_one(signal_doc)
            logger.info(
                f"Shortfall signal written for {state.entity_id}: "
                f"day {shortfall_day}, amount {shortfall_amount_usd}"
            )
