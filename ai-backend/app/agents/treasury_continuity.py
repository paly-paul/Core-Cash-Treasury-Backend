"""Agent 7: Treasury Continuity

Deterministic agent that finds historical precedents from MongoDB recommendations
collection matching current breach context. No LLM. Runs before Agent 6 in the pipeline.
"""
from typing import Dict, Any, List, Optional
from uuid import uuid4

from app.graph.state import AgentState


async def run_agent_7_continuity(state: AgentState) -> AgentState:
    """Run Treasury Continuity Agent."""
    try:
        from app.mongo.client import get_mongo_db

        mongo_db = get_mongo_db()
        agent = TreasuryContinuityAgent(mongo=mongo_db)
        result = await agent.run(state)
        state["treasury_continuity"] = result
        return state

    except Exception as e:
        state["errors"]["agent_7"] = str(e)
        return state


class TreasuryContinuityAgent:
    """Treasury Continuity Agent — finds historical precedents from recommendations."""

    def __init__(self, mongo):
        self.mongo = mongo

    async def run(self, state: AgentState) -> Dict[str, Any]:
        """
        Reads MongoDB recommendations collection only.
        PostgreSQL decision_log is deferred to Phase 2 — do NOT read or write decision_log.
        # TODO: add decision_log table and query in Phase 2
        """
        client_id = state["client_id"]

        # Get current breaches from Agent 3 output
        current_breaches = state.get("liquidity_risk", {}).get("active_breaches", [])

        if not current_breaches:
            return {
                "precedents": [],
                "pattern_notes": [],
            }

        precedents = await self._find_precedents(client_id, current_breaches)
        pattern_notes = self._detect_ar_patterns(state)

        return {
            "precedents": precedents,
            "pattern_notes": pattern_notes,
        }

    async def _find_precedents(
        self, client_id: str, current_breaches: list
    ) -> list:
        """
        For each current breach, find the 3 most recent approved recommendations
        of type 'Funding' for the same entity in the recommendations collection.
        """
        precedents = []
        seen_ids = set()

        for breach in current_breaches:
            entity_name = breach.get("entity_name")
            if not entity_name:
                continue

            # Find docs with approved Funding recs for this entity
            cursor = (
                self.mongo["recommendations"]
                .find(
                    {
                        "client_id": client_id,
                        "recommendations": {
                            "$elemMatch": {
                                "type": "Funding",
                                "approval_status": "Approved",
                            }
                        },
                    }
                )
                .sort("created_at", -1)
                .limit(5)
            )

            async for doc in cursor:
                for rec in doc.get("recommendations", []):
                    if (
                        rec.get("type") == "Funding"
                        and rec.get("approval_status") == "Approved"
                        and entity_name in rec.get("why", "")
                        and rec["id"] not in seen_ids
                    ):
                        seen_ids.add(rec["id"])
                        created_at = doc.get("created_at")
                        precedents.append(
                            {
                                "date": (
                                    created_at.date().isoformat()
                                    if created_at
                                    else None
                                ),
                                "entity_name": entity_name,
                                "situation": rec.get("why", ""),
                                "action_taken": rec.get("what", ""),
                                "outcome": rec.get("notes", "No outcome recorded"),
                                "relevance": (
                                    f"Current {entity_name} breach matches "
                                    f"this historical funding pattern."
                                ),
                            }
                        )
                        if len(precedents) >= 3:
                            return precedents

        return precedents

    def _detect_ar_patterns(self, state: AgentState) -> list:
        """
        Detect recurring AR delay patterns.
        In MVP: if Agent 3 shows AR concentration, note the top counterparty.
        Full pattern analysis deferred to Phase 2.
        # TODO: expand with time-series AR delay analysis in Phase 2
        """
        notes = []
        ar_conc = state.get("liquidity_risk", {}).get("ar_concentration_risk", {})
        top = ar_conc.get("top_counterparties", [])
        if top and ar_conc.get("high_single_counterparty"):
            notes.append(
                f"{top[0]['name']} represents {top[0]['share_pct']:.1f}% of "
                f"total AR — monitor for concentration and payment timing."
            )
        return notes
