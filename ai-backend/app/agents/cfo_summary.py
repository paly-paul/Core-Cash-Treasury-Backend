"""Agent 6: CFO Summary

LLM agent that composes CFO Summary report and Daily Briefing from prior agent outputs.
LLM is mocked with template strings in this session. Real Anthropic API wired in Session 12.
"""
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from uuid import uuid4
from decimal import Decimal

from app.graph.state import AgentState


async def run_agent_6_cfo_summary(state: AgentState) -> AgentState:
    """Run CFO Summary Agent."""
    try:
        from app.mongo.client import get_mongo_db
        from app.database import get_readonly_db

        mongo_db = get_mongo_db()
        pg_db = get_readonly_db()

        agent = CfoSummaryAgent(mongo=mongo_db, pg=pg_db)
        result = await agent.run(state)

        # Agent 6 writes TWO documents to MongoDB: cfo_reports + daily_briefings
        if "cfo_summary_doc" in result:
            await mongo_db["cfo_reports"].insert_one(result["cfo_summary_doc"])
        if "daily_briefing_doc" in result:
            await mongo_db["daily_briefings"].insert_one(result["daily_briefing_doc"])

        state["cfo_summary"] = result
        return state

    except Exception as e:
        state["errors"]["agent_6"] = str(e)
        return state


class CfoSummaryAgent:
    """CFO Summary Agent — composes summary report and daily briefing."""

    def __init__(self, mongo, pg):
        self.mongo = mongo
        self.pg = pg

    async def run(self, state: AgentState) -> Dict[str, Any]:
        """Compose CFO Summary and Daily Briefing from agent outputs."""
        client_id = state["client_id"]
        job_id = state["job_id"]

        # Extract agent outputs
        agent1_output = state.get("cash_position", {})
        agent3_output = state.get("liquidity_risk", {})
        agent7_output = state.get("treasury_continuity", {})

        # Compute cover values
        total_cash_usd = float(agent1_output.get("total_cash_usd", 0))
        usable_cash_usd = float(agent1_output.get("usable_cash_usd", 0))
        od_limit_total_usd = float(agent1_output.get("od_limit_total_usd", 0))
        od_headroom_total_usd = self._get_od_headroom_for_summary(agent1_output)
        overall_confidence = agent1_output.get("data_confidence", "Unknown")

        # Breach and recommendation counts
        active_breaches = agent3_output.get("active_breaches", [])
        breach_count = len(active_breaches)

        # Get latest recommendations
        latest_recs_doc = await self._get_latest_recommendations(client_id)
        rec_count = len(latest_recs_doc.get("recommendations", [])) if latest_recs_doc else 0
        approved_recs = [
            r
            for r in latest_recs_doc.get("recommendations", [])
            if r.get("approval_status") in ["Approved", "Overridden"]
        ][:10]

        # Compute MTD changes per entity
        cash_position_items = []
        for entity in agent1_output.get("entities", []):
            entity_name = entity.get("entity_name")
            usable_entity_usd = float(entity.get("usable_cash_usd", 0))

            mtd_result = await self._compute_mtd_change(entity_name, usable_entity_usd, client_id)
            cash_position_items.append(
                {
                    "entity_name": entity_name,
                    "usable_cash_usd": usable_entity_usd,
                    "mtd_change_usd": mtd_result.get("mtd_change_usd"),
                    "trend": mtd_result.get("trend", "Unknown"),
                }
            )

        # Compute cash runway
        daily_actuals = await self._get_daily_actuals(client_id)
        runway_result = self._compute_cash_runway(usable_cash_usd, daily_actuals, [])
        cash_runway_days = runway_result.get("cash_runway_days", 0)
        cash_runway_note = runway_result.get("cash_runway_note")

        # Compute cover status
        risk_level = agent3_output.get("risk_level", "Unknown")
        cover_status = self._compute_cover_status(risk_level, breach_count)

        # Generate mock narratives
        executive_summary = self._generate_executive_summary(
            {
                "usable_cash_usd": usable_cash_usd,
                "risk_level": risk_level,
                "breach_count": breach_count,
                "recommendation_count": rec_count,
                "active_breaches": active_breaches,
            }
        )

        # Build full CFO Summary document
        cfo_summary_doc = {
            "summary_id": str(uuid4()),
            "client_id": client_id,
            "agent": "cfo_summary",
            "job_id": job_id,
            "report_date": date.today().isoformat(),
            "created_at": datetime.utcnow(),
            "overall_confidence": overall_confidence,
            "cover": {
                "title": f"Daily Cash Report – {date.today().strftime('%d %B %Y')}",
                "total_cash_usd": round(total_cash_usd, 2),
                "usable_cash_usd": round(usable_cash_usd, 2),
                "od_limit_total_usd": round(od_limit_total_usd, 2),
                "od_headroom_total_usd": od_headroom_total_usd,
                "forecast_closing_7d_usd": None,  # null until Agent 2 unblocked
                "status": cover_status,
            },
            "executive_summary": executive_summary,
            "cash_position": cash_position_items,
            "forecast_outlook": [],  # empty until Agent 2 unblocked
            "actions_required": approved_recs,
            "variance_explanation": None,  # null until Agent 5 wired
            "data_caveats": agent1_output.get("stale_feeds", []),
            "source_references": await self._build_source_references(client_id),
        }

        # Build Daily Briefing document
        recent_statements = await self._get_recent_statements(client_id, days=4)
        daily_briefing_doc = self._generate_daily_briefing(
            agent1_output=agent1_output,
            agent3_output=agent3_output,
            continuity_output=agent7_output,
            recent_statements=recent_statements,
            client_id=client_id,
        )

        return {
            "cfo_summary_doc": cfo_summary_doc,
            "daily_briefing_doc": daily_briefing_doc,
        }

    def _get_od_headroom_for_summary(self, agent1_output: dict) -> Optional[float]:
        """Source OD headroom from Agent 1 output — do NOT recompute."""
        total = 0.0
        found = False
        for entity in agent1_output.get("entities", []):
            for acct in entity.get("accounts", []):
                h = acct.get("od_headroom")
                if h is not None:
                    total += float(h)
                    found = True
        return round(total, 2) if found else None

    async def _get_latest_recommendations(self, client_id: str) -> Optional[dict]:
        """Get the most recent completed recommendations from MongoDB."""
        doc = (
            await self.mongo["recommendations"]
            .find_one(
                {"client_id": client_id},
                sort=[("created_at", -1)],
            )
        )
        return doc

    async def _compute_mtd_change(
        self, entity_name: str, current_balance_usd: float, client_id: str
    ) -> dict:
        """
        MTD change = current balance − balance on 1st of current month (USD).
        NOT YTD. YTD must not appear anywhere in this codebase.
        """
        from sqlalchemy import text

        today = date.today()
        first_of_month = today.replace(day=1)

        # Query PostgreSQL for the statement on or just after the 1st
        stmt = self.pg.execute(
            text(
                """
            SELECT bs.closing_balance, bs.currency
            FROM bank_statement bs
            JOIN accounts a ON a.id = bs.account_id
            JOIN legal_entity le ON le.id = a.entity_id
            WHERE le.name = :entity_name
              AND le.client_id = :client_id
              AND bs.statement_date >= :first_of_month
            ORDER BY bs.statement_date ASC
            LIMIT 1
            """
            ),
            {
                "entity_name": entity_name,
                "client_id": client_id,
                "first_of_month": first_of_month,
            },
        ).fetchone()

        if not stmt:
            return {"mtd_change_usd": None, "trend": "Unknown"}

        month_start_balance = float(stmt[0])
        month_start_currency = stmt[1]

        # Use current balance as baseline for USD conversion
        # (real FX resolution deferred to Agent 1 infrastructure)
        if month_start_currency == "USD":
            month_start_usd = month_start_balance
        else:
            # Simple fallback: assume 1:1 for MVP
            month_start_usd = month_start_balance

        mtd_change = current_balance_usd - month_start_usd
        trend = (
            "Up"
            if mtd_change > 0
            else ("Down" if mtd_change < 0 else "Flat")
        )

        return {"mtd_change_usd": round(mtd_change, 2), "trend": trend}

    async def _get_daily_actuals(self, client_id: str) -> list:
        """Get last 30 days of actual outflows from bank_statement."""
        from sqlalchemy import text
        from datetime import timedelta

        today = date.today()
        thirty_days_ago = today - timedelta(days=30)

        rows = self.pg.execute(
            text(
                """
            SELECT bs.statement_date, bs.closing_balance
            FROM bank_statement bs
            WHERE bs.statement_date >= :start_date
              AND bs.statement_date <= :end_date
            ORDER BY bs.statement_date ASC
            """
            ),
            {"start_date": thirty_days_ago, "end_date": today},
        ).fetchall()

        # Compute daily outflows (closing balance deltas)
        actuals = []
        for i in range(1, len(rows)):
            prev_balance = float(rows[i - 1][1]) if rows[i - 1][1] else 0
            curr_balance = float(rows[i][1]) if rows[i][1] else 0
            outflow = max(0, prev_balance - curr_balance)
            actuals.append(
                {
                    "date": rows[i][0],
                    "outflow_usd": outflow,
                }
            )
        return actuals

    def _compute_cash_runway(
        self,
        usable_cash_usd: float,
        daily_actuals: list,
        forecast_outflows: list,
    ) -> dict:
        """
        Blended average daily outflow = (historical_avg + projected_avg) / 2.
        One-off outflows excluded: any single day where outflow > 10% of usable_cash.

        Until Agent 2 is unblocked: use historical_avg only (no forecast data).
        # TODO: include forecast_outflows once Agent 2 is live (Session 14)
        """
        if not usable_cash_usd or usable_cash_usd <= 0:
            return {
                "cash_runway_days": 999,
                "cash_runway_note": None,
            }

        significant_threshold = usable_cash_usd * 0.10
        excluded_notes = []

        # Historical 30-day average (exclude one-offs)
        clean_actuals = []
        for day in daily_actuals[-30:]:
            outflow = abs(day.get("outflow_usd", 0))
            if outflow > significant_threshold:
                day_str = day["date"].isoformat() if isinstance(day["date"], date) else str(day["date"])
                excluded_notes.append(
                    f"Excluded {day_str} one-off outflow of "
                    f"USD {outflow:,.0f} (>{10:.0f}% of usable cash)"
                )
            else:
                clean_actuals.append(outflow)

        historical_avg = sum(clean_actuals) / max(len(clean_actuals), 1)

        # Projected average — use 0 until Agent 2 available
        projected_avg = 0.0

        blended_avg = (
            (historical_avg + projected_avg) / 2
            if projected_avg
            else historical_avg
        )

        runway_days = (
            int(usable_cash_usd / blended_avg) if blended_avg > 0 else 999
        )

        return {
            "cash_runway_days": runway_days,
            "cash_runway_note": "; ".join(excluded_notes) if excluded_notes else None,
        }

    def _compute_cover_status(self, risk_level: str, breach_count: int) -> str:
        """Compute cover status based on risk level and breach count."""
        if risk_level == "High" or breach_count >= 2:
            return "Critical"
        elif risk_level == "Medium" or breach_count >= 1:
            return "Attention"
        else:
            return "Normal"

    def _generate_executive_summary(self, context: dict) -> str:
        """LLM MOCK — replace with Anthropic client call in Session 12."""
        usable = context["usable_cash_usd"]
        risk = context["risk_level"]
        breach_count = context["breach_count"]
        rec_count = context.get("recommendation_count", 0)

        breach_text = (
            f" {breach_count} threshold breach(es) require attention."
            if breach_count
            else " No active threshold breaches."
        )

        return (
            f"[MOCK CFO SUMMARY] Cash position stands at USD {usable:,.0f} usable. "
            f"Liquidity risk is {risk}.{breach_text} "
            f"{rec_count} recommendation(s) pending approval. "
            f"[Replace with Claude API call in Session 12]"
        )

    async def _build_source_references(self, client_id: str) -> list:
        """Build source references from latest bank statement uploads."""
        from sqlalchemy import text

        rows = self.pg.execute(
            text(
                """
            SELECT DISTINCT file_name, upload_timestamp
            FROM bank_statement
            WHERE client_id = :client_id
            ORDER BY upload_timestamp DESC
            LIMIT 1
            """
            ),
            {"client_id": client_id},
        ).fetchall()

        references = []
        if rows:
            for row in rows:
                file_name = row[0]
                timestamp = row[1]
                references.append(
                    {
                        "source": "Bank Balances (CSV)",
                        "file_name": file_name,
                        "timestamp": timestamp.isoformat() if timestamp else None,
                        "status": "Current",
                    }
                )
        return references

    async def _get_recent_statements(self, client_id: str, days: int = 4) -> list:
        """Get last N days of bank statements for daily briefing."""
        from sqlalchemy import text
        from datetime import timedelta

        today = date.today()
        start_date = today - timedelta(days=days)

        rows = self.pg.execute(
            text(
                """
            SELECT DISTINCT statement_date, SUM(closing_balance) as total_usd
            FROM bank_statement
            WHERE statement_date >= :start_date
              AND statement_date <= :end_date
            GROUP BY statement_date
            ORDER BY statement_date ASC
            """
            ),
            {"start_date": start_date, "end_date": today, "client_id": client_id},
        ).fetchall()

        statements = []
        for row in rows:
            stmt_date = row[0]
            total_usd = float(row[1]) if row[1] else 0
            statements.append(
                {
                    "date": stmt_date,
                    "total_usd": total_usd,
                }
            )
        return statements

    def _generate_daily_briefing(
        self,
        agent1_output: dict,
        agent3_output: dict,
        continuity_output: dict,
        recent_statements: list,
        client_id: str,
    ) -> dict:
        """LLM MOCK — replace with Anthropic client call in Session 12."""
        usable_cash = float(agent1_output.get("usable_cash_usd", 0))
        significant_threshold = usable_cash * 0.10 if usable_cash > 0 else 0

        # Behind Us: last N calendar days — PROSE ONLY, one string per day
        behind_us = []
        for stmt in recent_statements[-4:]:
            date_label = stmt["date"].strftime("%a %d %b")
            narrative = (
                f"[MOCK] Cash position on {date_label}: "
                f"USD {stmt.get('total_usd', 0):,.0f}. "
                f"[Replace with Claude API call in Session 12]"
            )

            # Attach precedent callout from Agent 7 if a match exists
            precedent_callout = None
            for precedent in continuity_output.get("precedents", []):
                if precedent["date"] == stmt["date"].isoformat():
                    precedent_callout = (
                        f"Last time {precedent['entity_name']} faced this situation "
                        f"({precedent['date']}): {precedent['action_taken']}"
                    )
                    break

            behind_us.append(
                {
                    "date": stmt["date"].isoformat(),
                    "date_label": date_label,
                    "narrative": narrative,  # STRING — not a nested object
                    "precedent_callout": precedent_callout,
                }
            )

        # Ahead of Us: next 4 calendar days — PROSE ONLY
        ahead_us = []
        today = date.today()
        for i in range(1, 5):
            future_date = today + timedelta(days=i)
            date_label = future_date.strftime("%a %d %b")

            # Major outflow alert: fires when any forecast outflow > 10% usable_cash
            # Until Agent 2 unblocked: major_outflow_alert is always null
            # TODO: populate from Agent 2 forecast in Session 14
            major_outflow_alert = None

            ahead_us.append(
                {
                    "date": future_date.isoformat(),
                    "date_label": date_label,
                    "narrative": (
                        f"[MOCK] Outlook for {date_label}. "
                        f"[Replace with Claude API call in Session 12]"
                    ),
                    "major_outflow_alert": major_outflow_alert,
                }
            )

        # if_nothing_changes: single prose string — NOT a structured object
        if_nothing_changes = (
            "[MOCK] If current cash position is maintained and no material "
            "unexpected outflows occur, the position should remain stable "
            "through the near term. [Replace with Claude API call in Session 12]"
        )

        return {
            "run_id": str(uuid4()),
            "client_id": client_id,
            "generated_at": datetime.utcnow(),
            "behind_us": behind_us,
            "ahead_of_us": ahead_us,
            "if_nothing_changes": if_nothing_changes,  # STRING, not an object
        }
