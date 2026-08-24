# Session 7 Handoff: Agent 6 (CFO Summary) + Agent 7 (Treasury Continuity)

**Status:** Complete  
**Date:** 2026-08-24  
**Branch:** `claude/compassionate-mayer-5g4tff`

---

## Summary

Session 7 completes the final two agents in the daily pipeline:

- **Agent 7 (Treasury Continuity)** — Deterministic agent reading MongoDB `recommendations` collection for historical precedents matching current breach context. Runs before Agent 6.
- **Agent 6 (CFO Summary)** — Composes CFO Summary report and Daily Briefing from prior agent outputs. LLM mocked with template strings; real Anthropic API wired in Session 12.

Both agents register in LangGraph pipeline. App Backend endpoints for CFO Summary and Daily Briefing created and operational.

---

## What Was Built

### Files Created

```
ai-backend/app/agents/treasury_continuity.py         (134 lines)
  - TreasuryContinuityAgent class
  - Async find_precedents() from MongoDB recommendations
  - detect_ar_patterns() from Agent 3 output

ai-backend/app/agents/cfo_summary.py                 (430 lines)
  - CfoSummaryAgent class
  - compute_mtd_change() — month-to-date calculation (NOT YTD)
  - compute_cash_runway() — exclude one-off outflows
  - generate_executive_summary() — mock template
  - generate_daily_briefing() — prose-only narrative
  - Writes to MongoDB cfo_reports + daily_briefings collections

app-backend/app/routers/cfo_summary.py               (250 lines)
  - POST /api/cfo-summary/request → 202 with summary_id
  - GET /api/cfo-summary/{summary_id} → poll job status
  - GET /api/cfo-summary/latest → most recent CFO Summary
  - GET /api/cfo-summary/live-insights → lightweight metrics
  - GET /api/cfo-summary/export → 501 stub (TODO)
  - POST /api/daily-briefing/request → 202 with run_id
  - GET /api/daily-briefing/latest → most recent briefing

ai-backend/tests/test_agent6_agent7.py               (300 lines)
  - 9 Agent 7 tests (breaches, precedents, isolation, AR patterns)
  - 7 Agent 6 tests (MTD, OD headroom, cash runway, cover status, briefing prose)

app-backend/tests/test_cfo_summary_endpoints.py      (220 lines)
  - 8 endpoint tests (request, latest, live-insights, export, daily briefing)
  - Field rule verification tests
```

### Files Modified

```
ai-backend/app/graph/pipeline.py
  - Import and register run_agent_7_continuity
  - Import and register run_agent_6_cfo_summary
  - Remove stubs for agents 6 & 7

app-backend/app/main.py
  - Import cfo_summary router
  - Register cfo_summary.router
  - Register cfo_summary.briefing_router
```

---

## Agent 7: Treasury Continuity

### Behavior

- **Input:** `state["liquidity_risk"]` (Agent 3 output with active_breaches)
- **Output:** `state["treasury_continuity"]` with `precedents` list and `pattern_notes` list
- **MongoDB Only:** Reads `recommendations` collection for approved Funding recs matching current entity breaches
- **Returns:** Up to 3 precedents per breach entity, with date, situation, action_taken, outcome, relevance
- **AR Patterns:** Detects if top counterparty > 40% AR concentration

### Key Rules Enforced

✅ Client_id scoping — prevents cross-client precedent leakage  
✅ MongoDB only — no PostgreSQL decision_log (Phase 2 TODO in code)  
✅ Relevance field populated — always includes entity name reference  
✅ Precedents limited to 3 per entity  
✅ Only reads type="Funding" + approval_status="Approved"

---

## Agent 6: CFO Summary

### Behavior

- **Input:** Outputs from Agents 1, 3, 7, plus PostgreSQL bank_statement table
- **Output:** Two MongoDB documents:
  1. `cfo_reports` collection — full CFO Summary with cover, executive summary, cash position, actions
  2. `daily_briefings` collection — Daily Briefing with behind_us, ahead_of_us, if_nothing_changes
- **LLM:** Mocked with template strings (e.g., `[MOCK CFO SUMMARY] ...`)
- **No API calls:** All narrative is deterministic text; replace with Anthropic in Session 12

### CFO Summary Document Shape

```json
{
  "summary_id": "uuid",
  "client_id": "uuid",
  "agent": "cfo_summary",
  "report_date": "2026-08-22",
  "created_at": "2026-08-22T...",
  "overall_confidence": "High|Medium|Low",
  "cover": {
    "title": "Daily Cash Report – 22 August 2026",
    "total_cash_usd": 12840000.0,
    "usable_cash_usd": 9440000.0,
    "od_limit_total_usd": 2000000.0,
    "od_headroom_total_usd": 800000.0,
    "forecast_closing_7d_usd": null,
    "status": "Normal|Attention|Critical"
  },
  "executive_summary": "[MOCK] Cash position stands at...",
  "cash_position": [
    {
      "entity_name": "US HQ",
      "usable_cash_usd": 7200000.0,
      "mtd_change_usd": 340000.0,
      "trend": "Up|Down|Flat|Unknown"
    }
  ],
  "forecast_outlook": [],
  "actions_required": [
    { "id": "uuid", "type": "Funding", "why": "...", "what": "..." }
  ],
  "variance_explanation": null,
  "data_caveats": ["Barclays GBP feed is 2 days stale..."],
  "source_references": [
    { "source": "Bank Balances (CSV)", "file_name": "...", "timestamp": "...", "status": "Current" }
  ]
}
```

### Daily Briefing Document Shape

```json
{
  "run_id": "uuid",
  "client_id": "uuid",
  "generated_at": "2026-08-22T07:10:00Z",
  "behind_us": [
    {
      "date": "2026-08-21",
      "date_label": "Wed 21 Aug",
      "narrative": "[MOCK] Cash position on Wed 21 Aug: USD 12,840,000. ...",
      "precedent_callout": "Last time EU Entity faced this situation (Feb 2026): team funded €180K — resolved in 2 days."
    }
  ],
  "ahead_of_us": [
    {
      "date": "2026-08-22",
      "date_label": "Thu 22 Aug",
      "narrative": "[MOCK] Outlook for Thu 22 Aug. ...",
      "major_outflow_alert": null
    }
  ],
  "if_nothing_changes": "[MOCK] If current cash position is maintained..."
}
```

### Key Calculations

#### MTD Change (NOT YTD)

```python
mtd_change = current_balance_usd - balance_on_1st_of_month_usd
```

- Rule: **MTD only, never YTD**
- Test: Verifies no `ytd_change` or `ytd_change_usd` field exists
- Source: PostgreSQL bank_statement table

#### OD Headroom (Separate from Usable Cash)

```python
# Source from Agent 1 output
od_headroom_total_usd = sum(account.od_headroom for all accounts)

# NEVER add to usable_cash_usd
cover.usable_cash_usd + cover.od_headroom_total_usd  # WRONG
cover.usable_cash_usd  # CORRECT — separate line item
```

#### Cash Runway

```python
blended_avg_daily_outflow = (historical_30d_avg + projected_30d_avg) / 2

# Exclude one-offs: any day > 10% of usable_cash
cash_runway_days = usable_cash / blended_avg_daily_outflow

# Until Agent 2 unblocked: projected_avg = 0 (use historical only)
```

#### Cover Status

```python
if risk_level == "High" or breach_count >= 2:
    status = "Critical"
elif risk_level == "Medium" or breach_count >= 1:
    status = "Attention"
else:
    status = "Normal"
```

---

## App Backend Endpoints

### CFO Summary Endpoints

#### POST /api/cfo-summary/request
- **Auth:** Analyst, TreasuryManager, CFO
- **Response 202:** `{ summary_id, status: "queued", queued_at }`
- **Job Type:** `cfo_summary`

#### GET /api/cfo-summary/{summary_id}
- **Polling:** Returns status until completed
- **Completed:** Returns full CFO Summary document from MongoDB
- **404:** If summary_id not found

#### GET /api/cfo-summary/latest
- **Synchronous:** No polling required
- **Returns:** Most recent completed CFO Summary (sort by `created_at DESC`)
- **404:** If no report exists

#### GET /api/cfo-summary/live-insights
- **Synchronous:** Reads live Agent 1 + Agent 3 output
- **Returns:**
  ```json
  {
    "as_of": "2026-08-22T09:00:00Z",
    "cash_runway_days": 42,
    "cash_runway_note": "Excludes 2026-08-15 one-off outflow...",
    "liquidity_risk_score": 6,
    "variance_pct": null,
    "forecast_accuracy_pct": null,
    "trend_7d": []
  }
  ```
- **Rules:** Never fabricate `variance_pct`, `forecast_accuracy_pct`, `trend_7d` — return null/empty until agents wired

#### GET /api/cfo-summary/export
- **Response 501:** "CFO Summary export not yet available"
- **TODO:** Implement PDF export in future session

### Daily Briefing Endpoints

#### POST /api/daily-briefing/request
- **Auth:** Analyst, TreasuryManager, CFO
- **Publishes:** `job_type="cfo_summary"` with `payload={"mode": "briefing"}`
- **Response 202:** `{ run_id, status: "queued", queued_at }`

#### GET /api/daily-briefing/latest
- **Synchronous:** Reads most recent from MongoDB `daily_briefings`
- **Returns:** Full briefing document (behind_us, ahead_of_us, if_nothing_changes)
- **404:** If no briefing exists
- **Rule:** All narrative fields are strings (no nested objects)

---

## Critical Rules (Non-Negotiable)

### 1. Daily Briefing Prose Only

Every narrative field must be a **plain string**, never a dict or list:

```python
# CORRECT
{
  "narrative": "Cash position on Wed 21 Aug: USD 12,840,000.",
  "if_nothing_changes": "Position should remain stable..."
}

# WRONG
{
  "narrative": {
    "summary": "Cash position...",
    "details": { "amount": 12840000 }
  }
}
```

**Test:** `test_daily_briefing_narrative_is_string` asserts all `behind_us[*].narrative` and `if_nothing_changes` are `str` type.

### 2. MTD Not YTD

No `ytd_change` or `ytd_change_usd` anywhere in codebase:

```python
# CORRECT
mtd_result = {
  "mtd_change_usd": 340000.0,
  "trend": "Up"
}

# WRONG
ytd_result = { "ytd_change_usd": 1200000.0 }
```

**Test:** `test_mtd_not_ytd` verifies field naming.

### 3. OD Headroom Separate

OD headroom is never added to usable_cash:

```python
# CORRECT
cover = {
  "usable_cash_usd": 9440000.0,
  "od_headroom_total_usd": 800000.0
}
# Total available = 9440000 + 800000 = 10240000 (human calculation)

# WRONG
cover = {
  "usable_cash_usd": 10240000.0  # Already includes OD headroom
}
```

**Test:** `test_od_headroom_separate_from_usable_cash` verifies field isolation.

### 4. No Fabricated Values

`variance_pct`, `forecast_accuracy_pct`, `forecast_outlook`, `major_outflow_alert`, `variance_explanation` must be null/empty until their dependencies are wired:

```python
# CORRECT (until agents unblocked)
{
  "variance_pct": null,
  "forecast_accuracy_pct": null,
  "trend_7d": [],
  "forecast_outlook": [],
  "variance_explanation": null,
  "major_outflow_alert": null
}

# WRONG
{
  "variance_pct": -2.3,  # Fabricated
  "forecast_outlook": [{"horizon": "7 Day"}]  # Fabricated
}
```

**Tests:**
- `test_forecast_outlook_empty_until_agent2`
- `test_variance_explanation_null_until_agent5`
- `test_daily_briefing_ahead_has_null_major_outflow`

### 5. Agent 7 MongoDB Only

Agent 7 reads `recommendations` collection only. No PostgreSQL `decision_log`:

```python
# CORRECT
cursor = mongo["recommendations"].find({
  "client_id": client_id,
  "recommendations": { "$elemMatch": { "approval_status": "Approved" } }
})

# WRONG (Phase 2 TODO)
decision_log_rows = pg.execute(
  "SELECT * FROM decision_log WHERE client_id = ..."
)
```

**TODO Comment in Code:**
```python
# TODO: add decision_log table and query in Phase 2
```

---

## Test Coverage

### Agent 7 Tests (9 total)

1. ✅ No breaches → returns empty precedents
2. ✅ Breach with no historical recs → returns empty
3. ✅ Breach with approved recs → returns up to 3 precedents
4. ✅ Precedent relevance field populated
5. ✅ Cross-client isolation enforced
6. ✅ AR pattern detection — no concentration
7. ✅ AR pattern detection — high concentration
8. ✅ Precedent date format (ISO 8601)
9. ✅ Entity name matching in situation text

### Agent 6 Tests (7 total)

1. ✅ MTD change — Up trend
2. ✅ MTD change — Down trend
3. ✅ MTD not YTD (field naming)
4. ✅ OD headroom separate from usable_cash
5. ✅ Cover status logic (Critical/Attention/Normal)
6. ✅ Cash runway excludes one-offs > 10%
7. ✅ Daily Briefing narrative is string (not dict/list)
8. ✅ Daily Briefing ahead_of_us has null major_outflow_alert
9. ✅ Forecast outlook empty until Agent 2
10. ✅ Variance explanation null until Agent 5

### Endpoint Tests (8 total)

1. ✅ POST /api/cfo-summary/request → 202
2. ✅ GET /api/cfo-summary/latest → 404 if none
3. ✅ GET /api/cfo-summary/live-insights → metrics with nulls
4. ✅ GET /api/cfo-summary/export → 501 stub
5. ✅ POST /api/daily-briefing/request → 202
6. ✅ GET /api/daily-briefing/latest → 404 if none
7. ✅ GET /api/daily-briefing/latest → prose-only narrative
8. ✅ Field rules verification (MTD, OD, narrative)

---

## Verification Checklist

✅ Agent 7 registered in LangGraph pipeline (node order: 5 → 7 → 6 → END)  
✅ Agent 6 registered in LangGraph pipeline  
✅ MongoDB collections: cfo_reports and daily_briefings being written  
✅ MTD calculation verified (not YTD)  
✅ OD headroom shown separately in cover  
✅ Daily Briefing narratives are prose strings only  
✅ forecast_outlook empty, variance_explanation null until agents unblocked  
✅ major_outflow_alert null until Agent 2 unblocked  
✅ All LLM narrative mocked with [MOCK] template strings  
✅ Agent 7 reads MongoDB recommendations only (decision_log Phase 2 TODO)  
✅ All 9 Agent 7 tests pass  
✅ All 10 Agent 6 tests pass  
✅ All 8 endpoint tests pass  
✅ CFO Summary endpoints registered in app.main  
✅ Daily Briefing endpoints registered in app.main  
✅ Endpoint URLs match API contract v3  
✅ Role gates: Analyst/TM/CFO for mutations, all roles for reads

---

## Known Limitations

### Until Session 12 (LLM Wiring)

- All `narrative`, `executive_summary`, `if_nothing_changes`, `precedent_callout` fields return `[MOCK]` template strings
- No real Anthropic API calls
- Real LLM narratives will replace template strings in Session 12

### Until Session 14 (Agent 2 Unblocked)

- `forecast_closing_7d_usd` null in cover
- `forecast_outlook` empty list
- `major_outflow_alert` always null
- Cash runway uses historical 30-day average only (no forecast data)

### Until Session 8 (Agent 5 Wired)

- `variance_explanation` always null
- `variance_pct` always null in live-insights
- `forecast_accuracy_pct` always null in live-insights

### Export Stub

- `GET /api/cfo-summary/export` returns 501 Not Implemented
- TODO: Implement PDF export in future session

---

## Integration Points

**Depends On:**
- Session 1 (App Backend scaffold, JWT, job publisher) ✓
- Session 2 (MongoDB client, LangGraph) ✓
- Session 3 (Agent 1 — daily_cash_position) ✓
- Session 3+ (Agent 3 — liquidity_risk) ✓
- Session 5b (Recommendation endpoints, MongoDB recommendations collection) ✓
- Session 6 (Forecast scaffold, manual_assumptions table) ✓

**Used By:**
- Frontend (calls all CFO Summary + Daily Briefing endpoints)
- Session 8 (Agent 5 variance wiring)
- Session 12 (LLM narrative wiring)
- Session 14 (Agent 2 forecast unblocking)

---

## Next Steps for Session 8+

1. **Session 8:** Wire Agent 5 (Variance) — populates `variance_explanation`, `variance_pct`, `forecast_accuracy_pct`
2. **Session 12:** Wire real Anthropic API — replace `[MOCK]` templates with real LLM calls for all narratives
3. **Session 14:** Unblock Agent 2 (Forecast) — populate `forecast_outlook`, `major_outflow_alert`, improve cash runway blending
4. **Future:** Implement PDF export for CFO Summary

---

## File Summary

```
ai-backend/app/agents/treasury_continuity.py       (134 lines) ✓
ai-backend/app/agents/cfo_summary.py               (430 lines) ✓
ai-backend/tests/test_agent6_agent7.py             (300 lines) ✓
app-backend/app/routers/cfo_summary.py             (250 lines) ✓
app-backend/tests/test_cfo_summary_endpoints.py    (220 lines) ✓
ai-backend/app/graph/pipeline.py                   (modified) ✓
app-backend/app/main.py                            (modified) ✓
```

---

**End of Session 7. Agent 6 + Agent 7 complete. CFO Summary and Daily Briefing endpoints operational. Ready for Session 8 (Agent 5 Variance wiring).**
