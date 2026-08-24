# Session 5a Handoff: Agent 4 (Action Recommendation) + Agent 8 (Policy Control)

**Status:** Complete  
**Date:** 2026-08-24

---

## What Was Built

### AI Backend: Agent 4 (Action Recommendation)

**File: `ai-backend/app/agents/action_recommendation.py`**

- Generates prioritised action recommendations from Agent 1 (cash position) and Agent 3 (liquidity risk) outputs
- Reads agent outputs from MongoDB only (never directly from PostgreSQL)
- Reads investment policy per entity from PostgreSQL (SELECT-only, is_active=TRUE)
- Reads system config significant_outflow_pct from PostgreSQL (default 10%)
- Implements three-priority recommendation logic:
  1. **Priority 1 (Funding):** One recommendation per active breach
  2. **Priority 2 (Investment):** One recommendation per entity with sustained surplus (>150% of min_threshold)
  3. **Priority 3 (Forecast Shortfall):** TODO — wired in Session 14 when Agent 2 completes
- Surplus detection: Static rule in Session 5a (usable_cash > 150% of total min_threshold). TODO: forecast-driven in Session 14
- **LLM is fully mocked** — all recommendation text comes from template strings (no Anthropic API calls)
- Downgraded investment recommendations when no policy is uploaded (no block, just flagged)
- Always sets `approval_status = "Pending"`, `approved_by = None`, `approved_at = None` on creation
- Caps recommendations at 10 (priority order enforced)
- Returns raw recommendation list to state for Agent 8 processing
- Missing Agent 1 or Agent 3 output: logs warning, sets `state["errors"]["agent_4"]`, returns empty list

### AI Backend: Agent 8 (Policy Control)

**File: `ai-backend/app/agents/policy_control.py`**

- Deterministic middleware (no LLM) that validates, rewrites, and filters all recommendations
- Runs after Agent 4 in the pipeline
- Enforces three core rules:
  1. **All four required fields present:** why, what, when, control (blocks if missing)
  2. **human_approval_required must be True** (blocks if False or missing — never auto-corrects)
  3. **Rewrite execution verbs** in 'what' field: Transfer→Evaluate transfer of, Execute→Evaluate, Send→Consider sending, Move→Consider moving, Initiate→Propose initiating, Pay→Evaluate payment of, Wire→Evaluate wiring, Remit→Consider remitting, Disburse→Evaluate disbursement of, Release→Consider releasing
  4. **Enforce approval_status = "Pending"** on all recommendations (resets from any other value)
- Returns tuple: (approved_recs, blocked_recs)
- Approved recs: written to MongoDB `recommendations` collection
- Blocked recs: logged for observability only (NOT persisted)
- Core Cash principle: Read-only intelligence layer. Agents recommend. Humans approve. Nothing executes autonomously.

### Pipeline Registration: `ai-backend/app/graph/pipeline.py`

- Imported Agent 4 and Agent 8 implementations
- Replaced stub `run_agent_4_recommendations` with real implementation
- Replaced stub `run_agent_8_policy_control` with real implementation
- LangGraph flow now complete: Agent 1 → Agent 3 → Agent 2 → Agent 4 → Agent 8 → Agent 5 → Agent 7 → Agent 6

### MongoDB Writes

**Collection: `recommendations`**

Only Agent 8-approved recommendations written. Document shape:

```python
{
    "job_id": str,
    "client_id": str,
    "agent": "action_recommendation",
    "created_at": datetime,
    "recommendation_count": int,  # count of approved recs only
    "recommendations": [
        {
            "id": str,  # UUID
            "priority": int,  # 1 or 2 in Session 5a
            "type": str,  # "Funding" | "Investment"
            "why": str,  # non-null, non-empty
            "what": str,  # non-null, evaluative language only (execution verbs rewritten)
            "when": str,  # non-null
            "control": {
                "approval_owner": str,
                "policy_check": str,  # "Pass" | "No investment SOP — surplus flagged only" | etc
                "human_approval_required": True,  # always True
            },
            "approval_status": "Pending",  # always "Pending" on create
            "approved_by": None,
            "approved_at": None,
        }
    ],
    "blocked_count": int,
    "blocked_reasons": list,  # for observability, not exposed to API
    "source_agent_runs": {
        "agent_1": str,  # MongoDB _id
        "agent_3": str,  # MongoDB _id
    },
}
```

---

## Tests

**File: `ai-backend/tests/test_agent4_agent8.py`**

**28 comprehensive test cases** covering:

### Agent 4 Tests (13 tests)
1. Breach recommendation — all 4 fields present
2. Breach recommendation — evaluative language (no execution verbs)
3. Investment with policy uploaded — contains "Evaluate investment" and "SOP uploaded"
4. Investment without policy — contains "No investment SOP" and "upload"
5. Investment always has human_approval_required=True
6. Priority ordering: 2 breaches + 1 surplus → [breach, breach, investment]
7. Cap at 10: 15 breaches → 10 recommendations
8. Surplus detection above 150% threshold
9. Surplus detection below threshold (no surplus)
10. Surplus excludes accounts with include_in_cash_position=False
11. Approval status always "Pending"
12. All generated recs have approval_status="Pending", approved_by=None, approved_at=None

### Agent 8 Tests (15 tests)
13. Clean recommendation passes unchanged
14. Missing 'why' field blocks
15. Missing 'control' field blocks
16. human_approval_required=False blocks
17. Missing human_approval_required blocks
18. Rewrite "Transfer" → "Evaluate transfer of"
19. Rewrite "Execute" → "Evaluate"
20. All 10 execution verbs rewritten (none block)
21. Verb rewriting is case-insensitive
22. Multiple errors all reported in blocked_reasons
23. Approval status enforced to "Pending"
24. Blocked recs not in approved list (len(approved) + len(blocked) == len(input))
25. Investment without policy passes Agent 8 (already downgraded by Agent 4)
26. human_approval_required=False cannot be auto-corrected (must block)
27. Run returns (approved, blocked) tuple

**Test Results:**
```
============================= 28 passed in 0.32s ==============================
```

All tests PASSED ✓

---

## Critical Rules Confirmed in Implementation

1. ✅ **All 4 required fields (why/what/when/control)** — Agent 8 blocks missing fields
2. ✅ **Execution verbs rewritten (not blocked)** — 10 verbs mapped to evaluative replacements
3. ✅ **human_approval_required = False → always blocked, never auto-corrected** — enforces control framework
4. ✅ **approval_status always Pending on create** — enforced by Agent 8 unconditionally
5. ✅ **Investment without policy → downgraded by Agent 4, passes Agent 8** — no double-blocking
6. ✅ **Blocked recs logged to state, not persisted to MongoDB** — audit trail only
7. ✅ **Surplus static rule (150% of min_threshold)** — TODO: forecast-driven in Session 14
8. ✅ **Recommendations capped at 10** — priority order maintained
9. ✅ **Priority ordering enforced** — breaches (priority 1) before investments (priority 2)
10. ✅ **Missing Agent 1/3 output handled gracefully** — warning logged, empty list returned, pipeline continues

---

## Mock Boundary

**Agent 4 LLM mocking:** All recommendation text (why/what/when) comes from template strings. The `build_breach_recommendation()` and `build_investment_recommendation()` functions contain `# LLM MOCK` comments marking where Anthropic API calls will be wired in Session 12. Production flag: `ANTHROPIC_API_KEY` remains a placeholder.

**Agent 8:** Fully deterministic — no mock needed.

---

## Files Created

```
ai-backend/app/agents/action_recommendation.py      (274 lines)
ai-backend/app/agents/policy_control.py             (154 lines)
ai-backend/tests/test_agent4_agent8.py              (612 lines)
docs/session-05a-handoff.md                         (this file)
```

---

## Files Modified

```
ai-backend/app/graph/pipeline.py                    — imported Agent 4/8, replaced stubs
ai-backend/tests/conftest.py                        — added for test path setup
```

---

## Integration Points

**Depends On:**
- Session 1 (monorepo, shared library, both service scaffolds) ✓
- Session 2 (AI Backend + LangGraph skeleton, MongoDB collections) ✓
- Session 3 (Agent 1 complete, bank_statement table, accounts table) ✓
- Session 4 (Agent 3 complete, liquidity risk output) ✓
- Session 9 (investment_policy table, audit_log table, system_config table) ✓

**Inputs to Agent 4:**
- MongoDB: Agent 1 output (daily_cash_position agent run)
- MongoDB: Agent 3 output (liquidity_risk agent run)
- PostgreSQL: investment_policy table (SELECT is_active per entity)
- PostgreSQL: system_config table (SELECT significant_outflow_pct)

**Outputs from Agent 4 → Agent 8:**
- State["action_recommendations"]["raw"] — raw recommendation list

**Outputs from Agent 8 → MongoDB:**
- MongoDB: recommendations collection (only approved recs)

**Next Session (Session 5b):**
- App Backend recommendation endpoints (approve/reject/list)
- Reads from MongoDB recommendations collection
- Writes approval events to audit_log

---

## Known Limitations & Session 14 TODO

1. **Forecast-driven surplus (Session 14):** Currently static rule (150% of min_threshold). When Agent 2 (Forecast) completes, Session 14 will wire forecast shortfall days into Agent 4 surplus detection. Look for comment: `# TODO: replace with forecast-driven surplus detection in Session 14`

2. **Forecast shortfall recommendations (Session 14):** Priority 2 bucket is empty with TODO comment. When Agent 2 output is available, Session 14 will wire shortfall recommendations.

3. **Mock LLM (Session 12):** Recommendation text is hardcoded template strings. Session 12 will wire real Anthropic API calls.

---

## Verification Checklist

- ✅ Agent 4 reads Agent 1 output from MongoDB (not recomputing)
- ✅ Agent 4 reads Agent 3 output from MongoDB (not recomputing)
- ✅ Agent 4 reads investment_policy from PostgreSQL (SELECT-only, is_active=TRUE)
- ✅ Agent 4 reads system_config from PostgreSQL (default to 10% if missing)
- ✅ All recommendation text comes from template strings (no API calls)
- ✅ Agent 8 validates all 4 required fields
- ✅ Agent 8 blocks if human_approval_required = False
- ✅ Agent 8 does NOT auto-correct human_approval_required
- ✅ Agent 8 rewrites 10 execution verbs (case-insensitive)
- ✅ Agent 8 enforces approval_status = "Pending"
- ✅ Agent 8 blocks write only approved recs to MongoDB
- ✅ Blocked recs logged, not persisted
- ✅ Surplus detection excludes non-included accounts
- ✅ Recommendations capped at 10
- ✅ Priority ordering: breaches → investments
- ✅ Missing Agent 1/3 output handled gracefully
- ✅ All 28 tests pass
- ✅ Pipeline registered (stubs replaced)
- ✅ MongoDB writes configured correctly

---

## Next Steps for Session 5b

1. Build App Backend recommendation endpoints:
   - `POST /api/recommendations/approve/{recommendation_id}` — update approval_status, approved_by, approved_at
   - `POST /api/recommendations/reject/{recommendation_id}` — set rejection status
   - `POST /api/recommendations/override/{recommendation_id}` — override approval with reason
   - `GET /api/recommendations/list` — poll current recommendations
2. Write audit_log events for approval/rejection/override actions
3. Implement recommendation status queries (Pending / Approved / Rejected / Overridden)

---

**End of Session 5a. Ready for handoff to Session 5b (Recommendation Endpoints).**
