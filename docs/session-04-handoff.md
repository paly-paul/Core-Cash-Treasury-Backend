# Session 4 Handoff: Agent 3 (Liquidity Risk)

**Status:** Complete  
**Date:** 2026-08-23

## What Was Built

### AI Backend: Agent 3 (Liquidity Risk)

**File: `ai-backend/app/agents/liquidity_risk.py`**
- Deterministic agent (no LLM) that computes liquidity risk score
- Reads Agent 1 output from MongoDB for active_breaches and stale_feeds
- Reads AR data from PostgreSQL (SELECT-only, filters on status IN ('Open', 'Overdue'))
- Computes risk score from 4 components: base (1) + breaches (0–6) + stale_feed (0–1) + AR_concentration (0–1) + shortfall (always 0 until Session 14)
- Applies caps: breach_points ≤ 6, total score ≤ 10
- Implements AR concentration risk: groups by counterparty, calculates top_3_share_pct, flags high_single_counterparty (>40%)
- Generates deterministic narrative (no LLM) based on risk_level and breaches/concentration/stale_feeds
- Writes full output to MongoDB `agent_runs` collection
- Returns 503-like error response if Agent 1 output unavailable (code: AGENT_ERROR)

**Pipeline Registration: `ai-backend/app/graph/pipeline.py`**
- Replaced stub `run_agent_3_liquidity_risk` with real implementation
- Imports `run_agent_3_liquidity_risk` from `app.agents.liquidity_risk`
- Registered in LangGraph as node in correct sequence (after Agent 1, before Agent 2)

### App Backend: Liquidity Risk Endpoints

**File: `app-backend/app/routes/liquidity_risk.py`**

1. **POST /api/liquidity-risk/request** (202 Accepted)
   - Creates job_status record (status=queued)
   - Publishes liquidity_risk job via InProcessJobPublisher
   - Returns: `{ request_id, status: "queued", queued_at }`

2. **GET /api/liquidity-risk/{request_id}** (200 / 404)
   - Polls job status from PostgreSQL job_status table
   - When status=pending: returns `{ request_id, status, queued_at }`
   - When status=completed: retrieves full Agent 3 output from MongoDB by result_id
   - Returns: full Agent 3 output shape or status envelope

3. **GET /api/liquidity-risk/current** (200 / 404)
   - Synchronous endpoint (no polling)
   - Reads latest completed Agent 3 output from MongoDB (agent="liquidity_risk", sort by as_of DESC)
   - Returns: full Agent 3 output shape or 404 with NOT_FOUND error

4. **GET /api/liquidity-risk/alerts** (200 / 404)
   - Returns critical subset from latest completed run
   - Fields: as_of, risk_level, critical_breaches (active_breaches), forecast_shortfall_days
   - Omits: risk_score, score_breakdown, ar_concentration_risk, narrative

**File: `app-backend/app/main.py`**
- Added import: `from app.routes import ... liquidity_risk`
- Registered router: `app.include_router(liquidity_risk.router)`

### Database & Fixtures

**AR Fixtures: `app-backend/app/utils/fixtures.py`**
- Added ARData import and SourceFile import
- Created source_file record for AR data
- Added 5 AR fixture rows (total ~1M USD equivalent):
  - Customer A: 340k USD (~34%)
  - GlobalTech Ltd: 210k USD (~21%)
  - Nordic AS: 140k GBP (~14% when converted to USD)
  - Acme Corp: 180k USD (~18%)
  - Beta GmbH: 130k EUR (~14% when converted to USD)
- Top 3 share: ~69% (just below 70% threshold, allows testing both sides)

### Shared Library

**File: `shared/core_cash_shared/error_codes.py`**
- Added: `AGENT_ERROR = "AGENT_ERROR"` (for missing Agent 1 output case)

**File: `shared/core_cash_shared/__init__.py`**
- Exported AGENT_ERROR in __all__

### Tests

**Agent 3 Unit Tests: `ai-backend/tests/test_agent3_liquidity_risk.py`**
- 19 test cases covering:
  - Risk score computation (base, breaches, stale, AR concentration, shortfall=0)
  - Score caps (breach_pts ≤ 6, total ≤ 10)
  - Stale feed threshold (>48h, not ≥48h)
  - AR concentration risk (empty, single counterparty >40%, top_3 >70%)
  - Narrative generation (Low/Medium/High risk, breach count, AR concentration, stale feeds)
  - Field name validation (ar_concentration_risk, not concentration_risk)
  - Column order for active_breaches
  - Shortfall always 0
  - Missing Agent 1 output handling
- **Result:** All 19 tests PASSED

**App Backend Logic Tests: `app-backend/tests/test_liquidity_risk_logic.py`**
- 7 test cases covering:
  - POST request payload structure
  - GET /current response shape with ar_concentration_risk field
  - GET /alerts response (critical subset only)
  - 404 response structure
  - CRITICAL: ar_concentration_risk field name validation
  - Shortfall always 0
  - Active breaches column order
- **Result:** All 7 tests PASSED

### Critical Rules Confirmed in Implementation

1. ✅ **ar_concentration_risk** — field name is correct (not concentration_risk), verified in tests
2. ✅ **shortfall_pts = 0** — hardcoded with TODO comment for Session 14
3. ✅ **Breach points capped at 6** — `min(len(active_breaches) * 2, 6)`
4. ✅ **Total score capped at 10** — `min(raw, 10)`
5. ✅ **Stale threshold: strictly > 48h** — `if hours_stale > 48` (not ≥)
6. ✅ **Agent 3 reads Agent 1 output** — queries MongoDB for prior run, no independent recomputation
7. ✅ **SELECT-only from PostgreSQL** — AR data query never uses INSERT/UPDATE/DELETE
8. ✅ **Active breaches column order** — entity_name → account_name → min_threshold → current_balance → shortfall → currency

---

## Test Results Summary

```
=== AI Backend Agent 3 Tests ===
tests/test_agent3_liquidity_risk.py::TestRiskScore (8 tests)
  ✓ test_score_no_breaches_no_stale_no_ar
  ✓ test_score_one_breach
  ✓ test_score_three_breaches_cap
  ✓ test_score_stale_feed_over_48h
  ✓ test_score_stale_feed_exactly_48h
  ✓ test_score_ar_concentration_above_70
  ✓ test_score_all_components_triggers_cap
  ✓ test_shortfall_pts_always_zero

tests/test_agent3_liquidity_risk.py::TestARConcentration (4 tests)
  ✓ test_ar_concentration_empty
  ✓ test_ar_concentration_single_counterparty_over_40
  ✓ test_ar_concentration_top_3_above_70
  ✓ test_ar_concentration_field_name

tests/test_agent3_liquidity_risk.py::TestNarrative (4 tests)
  ✓ test_narrative_low_risk
  ✓ test_narrative_with_breach
  ✓ test_narrative_ar_concentration_breached
  ✓ test_narrative_stale_feeds

tests/test_agent3_liquidity_risk.py::TestAgentIntegration (3 tests)
  ✓ test_agent_3_no_agent_1_output
  ✓ test_ar_concentration_field_name_in_output
  ✓ test_active_breaches_column_order

Result: 19 PASSED

=== App Backend Logic Tests ===
tests/test_liquidity_risk_logic.py (7 tests)
  ✓ test_liquidity_risk_request_payload
  ✓ test_liquidity_risk_current_response_structure
  ✓ test_liquidity_risk_alerts_response_structure
  ✓ test_liquidity_risk_404_response_structure
  ✓ test_ar_concentration_risk_field_name_critical
  ✓ test_shortfall_pts_zero_in_response
  ✓ test_active_breaches_column_order

Result: 7 PASSED
```

**Total: 26 tests, all PASSED ✓**

---

## Known Limitations & Session 14 TODO

1. **Shortfall Points (Session 14)**: Currently hardcoded to 0. When Agent 2 (Forecast) completes, Session 14 will wire forecast shortfall days into Agent 3 score calculation. Look for comment: `# TODO: wire shortfall_pts from Agent 2 forecast output in Session 14`

2. **Endpoint Tests**: Full endpoint integration tests require complex test setup (mock Cognito auth, MongoDB in test mode). Logic tests verify response structure and data flow; full E2E tests recommended in dedicated session.

3. **FX Rate Application**: AR amounts already include amount_usd field; FX conversion logic is implicit in fixture setup. Production will need live FX rates for local→USD conversion.

---

## Integration Points

**Depends On:**
- Session 1 (monorepo, shared library, both service scaffolds) ✓
- Session 2 (AI Backend + LangGraph skeleton, MongoDB collections) ✓
- Session 3 (Agent 1 complete, bank_statement table, accounts table, ar_data table) ✓

**Inputs to Agent 3:**
- PostgreSQL: ar_data table (SELECT only)
- MongoDB: Agent 1 output (daily_cash_position agent run)

**Outputs from Agent 3:**
- MongoDB: agent_runs collection (liquidity_risk agent run)
- App Backend reads and serves via REST endpoints

**Next Session (Session 5):**
- Agent 2 (Forecast Intelligence) — depends on Agent 1 data
- When Agent 2 completes, Session 14 will wire forecast shortfall into Agent 3 score

---

## Files Modified/Created

**Created:**
- `ai-backend/app/agents/liquidity_risk.py` (259 lines)
- `ai-backend/tests/test_agent3_liquidity_risk.py` (371 lines)
- `app-backend/app/routes/liquidity_risk.py` (175 lines)
- `app-backend/tests/test_liquidity_risk_logic.py` (262 lines)
- `docs/session-04-handoff.md` (this file)

**Modified:**
- `ai-backend/app/graph/pipeline.py` — imported and registered Agent 3
- `app-backend/app/main.py` — imported and registered liquidity_risk router
- `app-backend/app/utils/fixtures.py` — added AR data fixtures
- `app-backend/app/auth/dependencies.py` — fixed HTTPAuthenticationError import
- `app-backend/tests/conftest.py` — added environment variable setup for tests
- `shared/core_cash_shared/error_codes.py` — added AGENT_ERROR
- `shared/core_cash_shared/__init__.py` — exported AGENT_ERROR

---

## Verification Checklist

- ✅ Agent 3 reads Agent 1 output (not recomputing breaches)
- ✅ AR concentration uses AR data only (no AP, no cash balances)
- ✅ Field name ar_concentration_risk (not concentration_risk) — **critical**
- ✅ Shortfall points always 0 with TODO comment
- ✅ Breach points capped at 6
- ✅ Total score capped at 10
- ✅ Stale threshold strictly > 48h
- ✅ Active breaches in correct column order
- ✅ All 19 Agent 3 unit tests pass
- ✅ All 7 App Backend logic tests pass
- ✅ Pipeline registered (stub replaced)
- ✅ Endpoints wired into main.py
- ✅ AR fixtures created for testing

---

**End of Session 4. Ready for handoff to Session 5.**
