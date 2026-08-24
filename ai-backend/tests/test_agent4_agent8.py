"""Tests for Agent 4 (Action Recommendation) and Agent 8 (Policy Control).

22 comprehensive test cases covering:
- Agent 4: Breach and investment recommendations with priority ordering
- Agent 8: Validation, verb rewriting, and blocking logic
- Integration: End-to-end pipeline with policy controls
"""
import re
from datetime import datetime
from uuid import uuid4

import pytest

from app.agents.action_recommendation import (
    build_breach_recommendation,
    build_investment_recommendation,
    detect_surplus,
    generate_recommendations,
)
from app.agents.policy_control import (
    PolicyControlAgent,
    validate_and_rewrite,
)


class TestAgent4BriefRecommendations:
    """Agent 4 unit tests: Breach recommendation structure."""

    def test_breach_recommendation_all_fields_present(self):
        """Test 1: Breach rec has all 4 required fields."""
        breach = {
            "entity_name": "Entity A",
            "account_name": "Account 001",
            "currency": "USD",
            "shortfall": 50000,
            "min_threshold": 100000,
        }
        agent1_output = {}

        rec = build_breach_recommendation(breach, agent1_output)

        assert "why" in rec
        assert "what" in rec
        assert "when" in rec
        assert "control" in rec
        assert rec["why"] is not None and len(rec["why"]) > 0
        assert rec["what"] is not None and len(rec["what"]) > 0
        assert rec["when"] is not None and len(rec["when"]) > 0
        assert rec["control"] is not None

    def test_breach_recommendation_evaluative_language(self):
        """Test 2: Breach rec 'what' does NOT contain execution verbs."""
        breach = {
            "entity_name": "Entity A",
            "account_name": "Account 001",
            "currency": "USD",
            "shortfall": 50000,
            "min_threshold": 100000,
        }
        agent1_output = {}

        rec = build_breach_recommendation(breach, agent1_output)
        what = rec["what"].lower()

        forbidden_verbs = [
            "transfer", "execute", "send", "move", "initiate",
            "pay", "wire", "remit", "disburse", "release"
        ]
        for verb in forbidden_verbs:
            assert not re.search(rf"\b{verb}\b", what), f"Found '{verb}' in 'what'"

    def test_breach_recommendation_control_fields(self):
        """Test 8b: Breach rec control has approval_owner and human_approval_required."""
        breach = {
            "entity_name": "Entity A",
            "account_name": "Account 001",
            "currency": "USD",
            "shortfall": 50000,
            "min_threshold": 100000,
        }
        agent1_output = {}

        rec = build_breach_recommendation(breach, agent1_output)

        assert rec["control"]["human_approval_required"] is True
        assert rec["approval_status"] == "Pending"
        assert rec["approved_by"] is None
        assert rec["approved_at"] is None


class TestAgent4InvestmentRecommendations:
    """Agent 4 unit tests: Investment recommendation logic."""

    def test_investment_with_policy_uploaded(self):
        """Test 3: Investment with policy contains 'Evaluate investment' and SOP language."""
        entity = {
            "entity_id": str(uuid4()),
            "entity_name": "Entity B",
            "usable_cash_usd": 500000,
            "accounts": [{"min_threshold": 100000, "include_in_cash_position": True}]
        }
        surplus = {
            "entity_id": entity["entity_id"],
            "entity_name": entity["entity_name"],
            "usable_cash_usd": 500000,
            "surplus_usd": 400000,
            "min_threshold_total": 100000,
        }

        rec = build_investment_recommendation(entity, surplus, has_policy=True)

        assert "Evaluate investment" in rec["what"]
        assert "SOP uploaded" in rec["control"]["policy_check"]
        assert rec["control"]["human_approval_required"] is True

    def test_investment_without_policy(self):
        """Test 4: Investment without policy contains 'No investment SOP' and upload."""
        entity = {
            "entity_id": str(uuid4()),
            "entity_name": "Entity C",
            "usable_cash_usd": 500000,
            "accounts": [{"min_threshold": 100000, "include_in_cash_position": True}]
        }
        surplus = {
            "entity_id": entity["entity_id"],
            "entity_name": entity["entity_name"],
            "usable_cash_usd": 500000,
            "surplus_usd": 400000,
            "min_threshold_total": 100000,
        }

        rec = build_investment_recommendation(entity, surplus, has_policy=False)

        assert "No investment SOP" in rec["what"]
        assert "upload" in rec["what"].lower()
        assert "No investment SOP" in rec["control"]["policy_check"]

    def test_investment_always_human_approval_required(self):
        """Test 9b: Investment rec always has human_approval_required = True."""
        entity = {
            "entity_id": str(uuid4()),
            "entity_name": "Entity D",
            "usable_cash_usd": 500000,
            "accounts": [{"min_threshold": 100000, "include_in_cash_position": True}]
        }
        surplus = {
            "entity_id": entity["entity_id"],
            "entity_name": entity["entity_name"],
            "usable_cash_usd": 500000,
            "surplus_usd": 400000,
            "min_threshold_total": 100000,
        }

        rec_with_policy = build_investment_recommendation(entity, surplus, has_policy=True)
        rec_without_policy = build_investment_recommendation(entity, surplus, has_policy=False)

        assert rec_with_policy["control"]["human_approval_required"] is True
        assert rec_without_policy["control"]["human_approval_required"] is True


class TestAgent4SurplusDetection:
    """Agent 4 unit tests: Surplus detection logic."""

    def test_surplus_detection_above_threshold(self):
        """Test surplus detected when usable > 150% of min_threshold."""
        entity = {
            "entity_id": str(uuid4()),
            "entity_name": "Rich Entity",
            "usable_cash_usd": 300000,
            "accounts": [
                {
                    "min_threshold": 100000,
                    "include_in_cash_position": True,
                }
            ]
        }

        surplus = detect_surplus(entity, significant_outflow_pct=10.0)

        assert surplus is not None
        assert surplus["surplus_usd"] == 200000
        assert surplus["usable_cash_usd"] == 300000

    def test_surplus_detection_below_threshold(self):
        """Test no surplus when usable <= 150% of min_threshold."""
        entity = {
            "entity_id": str(uuid4()),
            "entity_name": "Normal Entity",
            "usable_cash_usd": 150000,
            "accounts": [
                {
                    "min_threshold": 100000,
                    "include_in_cash_position": True,
                }
            ]
        }

        surplus = detect_surplus(entity, significant_outflow_pct=10.0)

        assert surplus is None

    def test_surplus_excludes_non_included_accounts(self):
        """Test surplus calculation excludes accounts with include_in_cash_position=False."""
        entity = {
            "entity_id": str(uuid4()),
            "entity_name": "Mixed Entity",
            "usable_cash_usd": 300000,
            "accounts": [
                {
                    "min_threshold": 100000,
                    "include_in_cash_position": True,
                },
                {
                    "min_threshold": 100000,
                    "include_in_cash_position": False,
                }
            ]
        }

        surplus = detect_surplus(entity, significant_outflow_pct=10.0)

        # Only first account's threshold counted (100k), so 300k > 150k = surplus
        assert surplus is not None


class TestAgent4PriorityOrdering:
    """Agent 4 unit tests: Priority ordering and capping."""

    def test_priority_ordering_breaches_then_surplus(self):
        """Test 5: Two breaches + one surplus → [breach, breach, investment]."""
        agent1_output = {
            "entities": [
                {
                    "entity_id": str(uuid4()),
                    "entity_name": "Entity A",
                    "usable_cash_usd": 300000,
                    "accounts": [{"min_threshold": 100000, "include_in_cash_position": True}]
                }
            ]
        }
        agent3_output = {
            "active_breaches": [
                {
                    "entity_name": "Entity A",
                    "account_name": "Account 001",
                    "currency": "USD",
                    "shortfall": 50000,
                    "min_threshold": 100000,
                },
                {
                    "entity_name": "Entity A",
                    "account_name": "Account 002",
                    "currency": "GBP",
                    "shortfall": 30000,
                    "min_threshold": 80000,
                }
            ]
        }

        recs = generate_recommendations(
            agent1_output=agent1_output,
            agent3_output=agent3_output,
            investment_policy_by_entity={str(uuid4()): True},
            significant_outflow_pct=10.0,
        )

        # First two should be breaches, third should be investment
        assert len(recs) == 3
        assert recs[0]["type"] == "Funding"
        assert recs[1]["type"] == "Funding"
        assert recs[2]["type"] == "Investment"

    def test_cap_at_10_recommendations(self):
        """Test 6: 15 breaches capped to 10 recommendations."""
        agent1_output = {"entities": []}
        agent3_output = {
            "active_breaches": [
                {
                    "entity_name": f"Entity {i}",
                    "account_name": f"Account {i}",
                    "currency": "USD",
                    "shortfall": 10000,
                    "min_threshold": 50000,
                }
                for i in range(15)
            ]
        }

        recs = generate_recommendations(
            agent1_output=agent1_output,
            agent3_output=agent3_output,
            investment_policy_by_entity={},
            significant_outflow_pct=10.0,
        )

        assert len(recs) == 10


class TestAgent4ApprovalStatusFields:
    """Agent 4 unit tests: Approval status fields."""

    def test_approval_status_always_pending(self):
        """Test 8c: Every recommendation has approval_status='Pending'."""
        breach = {
            "entity_name": "Entity A",
            "account_name": "Account 001",
            "currency": "USD",
            "shortfall": 50000,
            "min_threshold": 100000,
        }
        agent1_output = {}

        rec = build_breach_recommendation(breach, agent1_output)

        assert rec["approval_status"] == "Pending"
        assert rec["approved_by"] is None
        assert rec["approved_at"] is None

    def test_all_generated_recs_have_pending_status(self):
        """Test 9: All generated recommendations have approval_status='Pending'."""
        agent1_output = {
            "entities": [
                {
                    "entity_id": str(uuid4()),
                    "entity_name": "Entity A",
                    "usable_cash_usd": 300000,
                    "accounts": [{"min_threshold": 100000, "include_in_cash_position": True}]
                }
            ]
        }
        agent3_output = {
            "active_breaches": [
                {
                    "entity_name": "Entity A",
                    "account_name": "Account 001",
                    "currency": "USD",
                    "shortfall": 50000,
                    "min_threshold": 100000,
                }
            ]
        }

        recs = generate_recommendations(
            agent1_output=agent1_output,
            agent3_output=agent3_output,
            investment_policy_by_entity={str(uuid4()): True},
            significant_outflow_pct=10.0,
        )

        for rec in recs:
            assert rec["approval_status"] == "Pending"
            assert rec["approved_by"] is None
            assert rec["approved_at"] is None


class TestAgent8Validation:
    """Agent 8 unit tests: Validation and blocking logic."""

    def test_clean_recommendation_passes(self):
        """Test 10: Valid rec passes unchanged."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Test action",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
            "approval_status": "Pending",
            "approved_by": None,
            "approved_at": None,
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is not None
        assert len(errors) == 0
        assert rewritten == rec

    def test_missing_why_field_blocks(self):
        """Test 14: Missing 'why' field blocks recommendation."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "what": "Test action",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is None
        assert "Missing required field: why" in errors

    def test_missing_control_field_blocks(self):
        """Test 15: Missing 'control' field blocks recommendation."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Test action",
            "when": "Today",
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is None
        assert "Missing required field: control" in errors

    def test_human_approval_required_false_blocks(self):
        """Test 16: human_approval_required=False blocks recommendation."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Test action",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": False,
            },
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is None
        assert "human_approval_required must be True" in errors

    def test_human_approval_required_missing_blocks(self):
        """Test 16b: Missing human_approval_required blocks."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Test action",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
            },
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is None
        assert "human_approval_required must be True" in errors


class TestAgent8ExecutionVerbRewriting:
    """Agent 8 unit tests: Execution verb rewriting."""

    def test_rewrite_transfer(self):
        """Test 11: 'Transfer' rewritten to 'Evaluate transfer of'."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Transfer EUR 200K to EU Entity",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is not None
        assert "Evaluate transfer of" in rewritten["what"]
        assert not re.search(r"\bTransfer\b", rewritten["what"])

    def test_rewrite_execute(self):
        """Test 12: 'Execute' rewritten."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Execute the payment immediately",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is not None
        assert "Evaluate" in rewritten["what"]
        assert not re.search(r"\bExecute\b", rewritten["what"])

    def test_all_execution_verbs_rewritten(self):
        """Test 13: All 10 execution verbs are rewritten, none block."""
        verbs = [
            "Transfer", "Execute", "Send", "Move", "Initiate",
            "Pay", "Wire", "Remit", "Disburse", "Release",
        ]

        for verb in verbs:
            rec = {
                "id": str(uuid4()),
                "priority": 1,
                "type": "Funding",
                "why": "Test reason",
                "what": f"{verb} funds immediately",
                "when": "Today",
                "control": {
                    "approval_owner": "Manager",
                    "policy_check": "Pass",
                    "human_approval_required": True,
                },
            }

            rewritten, errors = validate_and_rewrite(rec)

            assert rewritten is not None, f"{verb} caused blocking"
            assert len(errors) == 0
            assert not re.search(rf"\b{verb}\b", rewritten["what"]), f"{verb} not rewritten"

    def test_verb_rewriting_case_insensitive(self):
        """Test verb rewriting is case-insensitive."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "TRANSFER funds to account",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is not None
        assert "Evaluate transfer of" in rewritten["what"]


class TestAgent8MultipleErrors:
    """Agent 8 unit tests: Multiple errors reported."""

    def test_multiple_errors_all_reported(self):
        """Test 18: Multiple errors all included in blocked_reasons."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is None
        assert len(errors) >= 2
        assert any("why" in e for e in errors)
        assert any("what" in e for e in errors)


class TestAgent8ApprovalStatusEnforcement:
    """Agent 8 unit tests: Approval status enforcement."""

    def test_approval_status_enforced_to_pending(self):
        """Test 20: Agent 8 resets approval_status to 'Pending'."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Test action",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
            "approval_status": "Approved",
            "approved_by": "user123",
            "approved_at": "2026-08-24T10:00:00Z",
        }

        rewritten, errors = validate_and_rewrite(rec)

        assert rewritten is not None
        assert rewritten["approval_status"] == "Pending"
        assert rewritten["approved_by"] is None
        assert rewritten["approved_at"] is None


class TestAgent8PolicyControl:
    """Agent 8 unit tests: Policy control run."""

    def test_blocked_recs_not_in_approved(self):
        """Test 21: Blocked recs in blocked list, not approved."""
        recs = [
            {
                "id": str(uuid4()),
                "priority": 1,
                "type": "Funding",
                "why": "Test reason",
                "what": "Test action",
                "when": "Today",
                "control": {
                    "approval_owner": "Manager",
                    "policy_check": "Pass",
                    "human_approval_required": True,
                },
            },
            {
                "id": str(uuid4()),
                "priority": 1,
                "type": "Funding",
                "when": "Today",
                "control": {
                    "approval_owner": "Manager",
                    "policy_check": "Pass",
                    "human_approval_required": True,
                },
            }
        ]

        agent = PolicyControlAgent()
        approved, blocked = agent.run(recs)

        assert len(approved) == 1
        assert len(blocked) == 1
        assert len(approved) + len(blocked) == len(recs)

    def test_investment_without_policy_passes_agent8(self):
        """Test 19: Investment without policy passes Agent 8 (already downgraded)."""
        rec = {
            "id": str(uuid4()),
            "priority": 2,
            "type": "Investment",
            "why": "Entity has sustained surplus",
            "what": "Surplus flagged only. No investment SOP uploaded.",
            "when": "Review before EOD",
            "control": {
                "approval_owner": "Treasury Manager",
                "policy_check": "No investment SOP — surplus flagged only",
                "human_approval_required": True,
            },
        }

        agent = PolicyControlAgent()
        approved, blocked = agent.run([rec])

        assert len(approved) == 1
        assert len(blocked) == 0


class TestAgent8HumanApprovalNotAutoCorrect:
    """Agent 8 unit tests: human_approval_required cannot be auto-corrected."""

    def test_human_approval_false_not_autocorrected(self):
        """Test 17: human_approval_required=False cannot be corrected to True — must block."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Test action",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": False,
            },
        }

        rewritten, errors = validate_and_rewrite(rec)

        # Must be blocked, not auto-corrected
        assert rewritten is None
        assert "human_approval_required must be True" in errors


class TestAgent8OutputStructure:
    """Agent 8 unit tests: Output structure."""

    def test_run_policy_control_returns_tuple(self):
        """Test policy control returns (approved, blocked) tuple."""
        rec = {
            "id": str(uuid4()),
            "priority": 1,
            "type": "Funding",
            "why": "Test reason",
            "what": "Test action",
            "when": "Today",
            "control": {
                "approval_owner": "Manager",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
        }

        agent = PolicyControlAgent()
        result = agent.run([rec])

        assert isinstance(result, tuple)
        assert len(result) == 2
        approved, blocked = result
        assert isinstance(approved, list)
        assert isinstance(blocked, list)
