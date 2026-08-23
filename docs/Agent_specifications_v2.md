# Core Cash — Agent Specifications

**Version**: 2.1
**Date**: 22 August 2026
**Status**: Ready for LangGraph implementation (S2–S15)
**Changes from v2.0**: Added `od_headroom` to Agent 1 account output; added dual-service deployment note; version bump.
**Audience**: LangGraph engineer, backend engineers

> **Deployment**: All agents run in the **AI Backend** (FastAPI + LangGraph). Agent outputs are written to MongoDB. App Backend reads results via GET endpoints. Neither agent code nor LangGraph state machines belong in the App Backend.

---

## Overview

Core Cash has 8 agents. Each agent is responsible for a specific decision domain. This document defines each agent's responsibility, inputs, output shape, frontend surfaces, dependencies, guardrails, and LLM vs. deterministic boundaries.

**Execution order** (sequential for MVP):
1. Daily Cash Position (leaf — no agent dependencies)
2. Liquidity Risk (depends on: Daily Cash Position)
3. Forecast Intelligence (depends on: Daily Cash Position)
4. Action Recommendation (depends on: Daily Cash Position, Liquidity Risk, Forecast Intelligence)
5. Variance Explanation (depends on: Daily Cash Position, Forecast Intelligence)
6. CFO Summary (depends on: all above)
7. Treasury Continuity (depends on: decision history store)
8. Policy-aware Control (middleware — validates output of Agent 4 before surfacing)

**Parallelisation (Phase 2)**: Agents 2 and 3 (Liquidity Risk + Forecast Intelligence) can run in parallel once Agent 1 completes. Sequential for MVP to reduce complexity.

---

## Cross-Cutting Rules (Apply to All Agents)

1. **Why / What / When / Control**: Every recommendation output must include all four fields. No exceptions.
2. **Read-only**: No agent initiates fund movement or payment. Agents recommend and draft; humans approve.
3. **Predictions ≠ Forecasts**: Pattern signals (Agent 2, pattern mode) live on `/trends/predictions` — never merged with forecast output on `/forecast`.
4. **Validated data only**: Agents consume data from the normalized cash model only. No agent reads raw uploaded files.
5. **Evaluative language**: Recommendation text uses Evaluate / Consider / Review / Propose / Escalate. Never Transfer / Execute / Send / Move / Initiate.
6. **Explainability required**: Every agent output includes rationale, not just the result.
7. **Unexplained Variance**: Agent 5 must not force variance drivers to sum to zero. Residual = Unexplained Variance.
8. **Traceability**: Every agent run produces a `run_id`. All outputs reference their `run_id` for audit.
9. **Recommendation cap**: Agent 4 outputs a maximum of 10 recommendation items per run.
10. **Confidence ≥ 50%**: Only manual assumptions with confidence ≥ 50% are fed into agents. Assumptions below threshold are excluded at the data preparation layer before agents run.

---

## Agent 1: Daily Cash Position

**Responsibility**: Produce the authoritative consolidated cash position across all entities, banks, accounts, and currencies at a point in time.

**Type**: Deterministic (no LLM required).

**Inputs**:
- `Statement` table: latest `closing_balance` and `available_balance` per account
- `Account` table: `currency`, `restricted_flag`, `od_limit`, `od_utilised_amount`, `min_threshold`, `entity_id`, `refresh_frequency`, `include_in_cash_position`
- `fx_rates` table: today's rates (or prior day with warning if today's not entered)
- `LegalEntity` table: entity metadata

**Output shape**:
```json
{
  "run_id": "uuid",
  "as_of": "2026-08-21T09:00:00Z",
  "fx_rates_date": "2026-08-21",
  "fx_rates_warning": false,
  "total_cash_usd": 12840000,
  "available_cash_usd": 12840000,
  "restricted_cash_usd": 3400000,
  "usable_cash_usd": 9440000,
  "od_limit_total_usd": 2000000,
  "data_confidence": "High",
  "stale_feeds": [],
  "missing_feeds": [],
  "entities": [
    {
      "entity_id": "uuid",
      "entity_name": "US HQ",
      "base_currency": "USD",
      "closing_balance_local": 7200000,
      "available_balance_local": 7200000,
      "restricted_balance_local": 0,
      "od_limit_local": 0,
      "usable_cash_local": 7200000,
      "usable_cash_usd": 7200000,
      "accounts": [
        {
          "account_id": "uuid",
          "account_name": "JPM USD Main",
          "bank": "JPMorgan",
          "currency": "USD",
          "closing_balance": 7200000,
          "available_balance": 7200000,
          "od_limit": null,
          "od_utilised": false,
          "od_headroom": null,
          "min_threshold": 2000000,
          "restricted_flag": false,
          "status": "Green",
          "confidence": "High",
          "statement_date": "2026-08-20",
          "hours_stale": 14
        }
      ]
    }
  ],
  "by_currency": [
    {
      "currency": "USD",
      "available_balance_local": 9100000,
      "available_balance_usd": 9100000,
      "share_pct": 70.8
    },
    {
      "currency": "GBP",
      "available_balance_local": 2700000,
      "available_balance_usd": 3429000,
      "share_pct": 26.7
    }
  ],
  "active_breaches": [
    {
      "entity_name": "EU Entity",
      "account_name": "BofA EUR Reserve",
      "min_threshold": 500000,
      "current_balance": 430000,
      "shortfall": 70000,
      "currency": "EUR"
    }
  ]
}
```

**`od_headroom` computation**: Agent computes this inline — it is never stored in the database.
```
od_headroom = od_limit − od_utilised_amount   (when od_limit IS NOT NULL)
od_headroom = null                             (when od_limit IS NULL — no OD facility)
```
`od_headroom` must never be added to `usable_cash`. OD headroom is always displayed separately.

**Account filtering**: Only accounts where `include_in_cash_position = TRUE` are included in `usable_cash_usd` and the entity rollup. Restricted/petty cash accounts with `include_in_cash_position = FALSE` are excluded from usable cash totals but must still appear in the account list with a clear exclusion flag.

**Status logic (per account)**:
```
Green  : available_balance >= min_threshold
Yellow : available_balance >= min_threshold × 0.70
Red    : available_balance < min_threshold × 0.70
```

**OD handling**: If `closing_balance < 0`, set `od_utilised = true`. If `od_limit` is configured, compute `od_headroom = od_limit − od_utilised_amount`. Include in account output. Never merge into Usable Cash.

**Data Confidence logic**:
```
All Daily accounts refreshed within 24h, no missing  → High
Any Daily account 24–48h stale OR one feed missing   → Medium
Any Daily account >48h stale OR multiple missing     → Low
```
Manual feeds (accounts with `refresh_frequency = Manual`): not assessed for staleness; always show as High confidence.
Manual-upload feeds (CSV files uploaded by user): High if ≤7 days old; Low if >7 days.

**Frontend surfaces**: Dashboard (all sections), CFO Summary (Section 4.4), Daily Briefing (opening context).

**Guardrails**:
- Never use `available_balance` from a statement older than 7 days without Low confidence flag
- Never merge OD Limit into Usable Cash figure
- FX rate warning must propagate to all USD-equivalent figures if today's rate is missing
- `od_headroom` must never be stored — compute in agent, return in output only

**Changes from v2.0**:
- `od_headroom` added to account output shape (nullable, computed inline)
- `include_in_cash_position` added to inputs; account filtering rule added
- `od_utilised_amount` added to inputs (was implied; now explicit)
- `od_headroom` computation rule and guardrail made explicit

---

## Agent 2: Forecast Intelligence

**Responsibility**: Produce 7, 30, and 60-day forward cash flow forecasts per entity, and (in pattern signals mode) detect recurring cash flow patterns.

**Type**: Deterministic (core calculation) + LLM optional (narrative explanation of forecast assumptions).

**⚠️ BLOCKED**: Opening balance logic is unresolved. Do not implement until Paul + amit j confirm the opening balance anchor rule. See backend-build-handoff.md Step 4.

**Inputs**:
- Agent 1 output (cash position as of run time)
- `ar_schedule` table: expected AR receipts by entity, counterparty, date, amount, currency
- `ap_schedule` table: expected AP payments by entity, vendor, date, amount, currency
- `manual_assumptions` table: filtered to `confidence_pct >= 50` only
- `fx_rates` table

**Forecast Confidence**: Not in MVP scope — deferred to Phase 2.

**Output shape**:
```json
{
  "run_id": "uuid",
  "triggered_by": "scheduled | ap_upload | assumption_change",
  "as_of": "2026-08-21T09:00:00Z",
  "opening_balance_date": "2026-08-20",
  "opening_balance_note": "Prior-day closing balance from last ingested statement — [RULE TBD]",
  "horizons": [
    {
      "horizon_days": 7,
      "opening_cash_usd": 12840000,
      "expected_inflows_usd": 2100000,
      "expected_outflows_usd": 1800000,
      "forecast_closing_usd": 13140000,
      "daily_positions": [
        {
          "date": "2026-08-22",
          "opening_usd": 12840000,
          "inflows_usd": 340000,
          "outflows_usd": 280000,
          "closing_usd": 12900000,
          "significant_outflow_flag": false,
          "breach_flag": false
        }
      ],
      "entities": [
        {
          "entity_name": "US HQ",
          "base_currency": "USD",
          "opening_local": 7200000,
          "inflows_local": 1200000,
          "outflows_local": 980000,
          "closing_local": 7420000,
          "status": "Green"
        }
      ]
    }
  ],
  "significant_outflows": [
    {
      "date": "2026-08-25",
      "amount_usd": 1200000,
      "pct_of_usable_cash": 12.7,
      "category": "Tax",
      "entity": "US HQ",
      "description": "Q3 estimated tax payment"
    }
  ],
  "inflow_categories": ["AR", "Loan Drawdown", "Investment Redemption", "Manual Assumption"],
  "outflow_categories": ["AP", "Payroll", "Tax", "Bank Fee", "Investment Placement", "Loan Repayment", "Capex", "Manual Assumption"]
}
```

**Significant outflow flag**:
```
Flag if any single-day outflow > 10% of Usable Cash (Rule A — operational)
```

**Inflow / Outflow classification**:
- Investment redemptions / maturity proceeds → Inflow
- New investment placements → Outflow
- Loan drawdowns → Inflow
- Loan repayments → Outflow

**Assumption filtering**: Only `manual_assumptions` where `confidence_pct >= 50` are included. Threshold is stored in system config (`forecast_confidence_threshold`, default 50).

**Forecast re-trigger events**:
- New AP file uploaded
- Manual assumption created, updated, or deleted
- Does NOT re-trigger on AR file upload or daily bank statement ingestion (scheduled run only)

**Pattern signals mode** (separate invocation — output to `/trends/predictions` only, never to `/forecast`):
- Detects recurring AR delays, AP early settlements, seasonal patterns
- Returns pattern signals with confidence label and suggested adjustment
- Never merged with forecast output

**Entity Forecast Table**: Values in entity's base currency. Status uses 70% threshold.

**Changes from v1.0**:
- Significant outflow flag added (10% of Usable Cash)
- Investment classification clarified (redemptions = Inflow; placements = Outflow)
- Loan repayments explicitly in Outflows
- Assumption confidence filter: ≥50% (was no explicit filter)
- Entity Forecast Table: base currency (was USD)
- Status: 70% threshold (was 80%)
- Forecast Confidence metric: deferred — not in output

---

## Agent 3: Liquidity Risk

**Responsibility**: Score and explain current liquidity risk across threshold breaches, AR concentration, stale data, and forecast shortfalls.

**Type**: Deterministic (scoring) + LLM optional (narrative risk summary).

**Inputs**:
- Agent 1 output (cash position, breaches, feed confidence)
- Agent 2 output (7-day forecast, shortfall flags)
- `ar_schedule` table (for AR concentration calculation)

**Output shape**:
```json
{
  "run_id": "uuid",
  "as_of": "2026-08-21T09:00:00Z",
  "risk_score": 6,
  "risk_level": "Medium",
  "score_breakdown": {
    "base": 1,
    "breach_points": 2,
    "stale_feed_points": 1,
    "ar_concentration_points": 1,
    "shortfall_points": 1,
    "raw_total": 6,
    "capped_at_10": false
  },
  "active_breaches": [
    {
      "entity_name": "EU Entity",
      "account_name": "BofA EUR Reserve",
      "min_threshold": 500000,
      "current_balance": 430000,
      "shortfall": 70000,
      "currency": "EUR"
    }
  ],
  "forecast_shortfall_days": ["2026-08-25", "2026-08-26"],
  "ar_concentration_risk": {
    "top_3_share_pct": 69.0,
    "threshold_pct": 70.0,
    "breached": false,
    "top_counterparties": [
      {"name": "Customer A", "share_pct": 34.0},
      {"name": "GlobalTech Ltd", "share_pct": 21.0},
      {"name": "Nordic AS", "share_pct": 14.0}
    ]
  },
  "stale_feeds": [
    {"account_name": "Barclays GBP Ops", "hours_stale": 51, "confidence": "Low"}
  ],
  "narrative": "Liquidity risk is Medium. One active breach in EU Entity (€70K shortfall). Forecast shortfall projected on 25–26 Aug if no funding action taken. AR concentration below 70% threshold — no alert. One stale feed (Barclays GBP)."
}
```

**Risk Score calculation**:
```
Base Score  = 1
Breach      = +2 per active breach of min_threshold, capped at 6
              (i.e., 3+ breaches = max 6 points from this component)
Stale feed  = +1 if any bank feed >48h stale
AR conc.    = +1 if top 3 counterparties > 70% of total AR outstanding
Shortfall   = +2 if any day in 7-day forecast has projected usable cash < min_threshold
Raw total   = sum of all above; if raw > 10, display as 10

Scale:
  1–3  = Low risk (Green)
  4–6  = Medium risk (Yellow)
  7–10 = High risk (Red)
```

**AR Concentration Risk**:
```
Concentration (%) = Sum(AR outstanding, top 3 counterparties) / Total AR outstanding × 100
Breached if Concentration > 70%
Single counterparty flag if any one > 40%
Label: "AR Concentration Risk" (not "Concentration Risk")
```

**Changes from v1.0**:
- Risk score: breach +2 (was +3); shortfall +2 (was +1)
- Score capped at 10 (truncate)
- AR Concentration Risk label corrected
- Active Breaches column order: entity → account → threshold → balance → shortfall → currency
- AR concentration calculation: AR only (not cash, not AP)

---

## Agent 4: Action Recommendation

**Responsibility**: Generate the next-best treasury action recommendations with mandatory Why / What / When / Control structure.

**Type**: LLM-driven (Claude 3.5 Sonnet for reasoning and recommendation drafting) + deterministic guardrails.

**⚠️ PARTIAL BLOCK**: Investment recommendation logic blocked until amit j provides (a) investment cut-off time values per entity, and (b) investment policy document. Deficit/funding recommendations are build-ready.

**⚠️ LLM MOCK**: In build sessions S0–S14, Agents 4, 5, and 6 use mock template strings in place of real LLM calls. `ANTHROPIC_API_KEY` is a `.env` placeholder. Real API is wired in S15 only.

**Inputs**:
- Agent 1 output (cash position)
- Agent 2 output (forecast, significant outflow flags)
- Agent 3 output (risk score, active breaches, shortfall days)
- Agent 8 output (Policy-aware Control — validates before surfacing)
- `investment_policy` config (uploaded SOP document; nullable — if null, surplus-flag-only mode)
- `entity_investment_cutoffs` config (cut-off time per entity; editable by admin)
- `doa_policy` config (approval hierarchy; editable by admin)

**Output shape**:
```json
{
  "run_id": "uuid",
  "generated_at": "2026-08-21T09:05:00Z",
  "recommendation_count": 2,
  "recommendations": [
    {
      "id": "uuid",
      "priority": 1,
      "type": "Funding",
      "why": "EU Entity EUR balance is €70K below the €500K minimum threshold. €120K AP run is due Friday 23 Aug, which will widen the shortfall to €190K without action.",
      "what": "Evaluate EUR 200K funding transfer to EU Entity BofA EUR Reserve from UK Operations Barclays GBP pool, subject to Finance Director approval per DOA policy.",
      "when": "Today by 14:00 EST (EU Entity investment cut-off). Delay past cut-off means earliest settlement is next business day.",
      "control": {
        "approval_owner": "Finance Director (per DOA policy)",
        "policy_check": "Pass — restricted account: no; minimum balance post-transfer: UK Operations remains above threshold",
        "human_approval_required": true
      },
      "approval_status": "Pending",
      "approved_by": null,
      "approved_at": null
    },
    {
      "id": "uuid",
      "priority": 2,
      "type": "Investment",
      "why": "US HQ USD balance has remained $2.1M above minimum threshold for 9 consecutive days. No material outflows projected in next 7 days.",
      "what": "Evaluate investment of surplus USD ~$2.0M from US HQ JPM USD Main per uploaded investment SOP. Review eligible instruments and cut-off times before acting.",
      "when": "Before 16:00 EST today (US HQ investment cut-off).",
      "control": {
        "approval_owner": "Treasury Manager (per DOA policy)",
        "policy_check": "Pass — investment SOP uploaded (v2, Jan 2026); surplus confirmed by 7-day forecast",
        "human_approval_required": true
      },
      "approval_status": "Pending",
      "approved_by": null,
      "approved_at": null
    }
  ]
}
```

**Investment recommendation rules**:
- Triggered when surplus cash > min_threshold for 7+ consecutive forecast days
- Requires `investment_policy` to be uploaded by admin; if null → surface surplus flag only, no vehicle recommendation
- Cut-off time sourced from `entity_investment_cutoffs` at entity level
- One designated investment account per entity irrespective of currency
- Language: "Evaluate investment of surplus [amount] per uploaded investment SOP" — never specify a vehicle unless SOP defines it

**Recommendation cap**: Maximum 10 items per run. Priority ranked by urgency (breach > shortfall > surplus investment opportunity).

**Approval workflow**:
- All recommendations start in `approval_status: Pending`
- User must explicitly approve, reject, or mark complete via UI
- No recommendation moves to executed state autonomously
- Approval recorded with `approved_by` (user ID) and `approved_at` timestamp

**Why / What / When / Control — enforcement**:
All four fields are required on every recommendation object. Agent must not return a recommendation with any field null or empty. Policy-aware Control Agent (Agent 8) blocks recommendations that fail this check before they surface.

**Changes from v1.0**:
- Language enforced as evaluative (Evaluate / Consider / Review / Propose / Escalate)
- Investment recommendations added with SOP requirement
- Cut-off time: entity-level configuration (not currency/bank)
- Approval hierarchy: DOA-based, admin-editable
- Output cap: 10 recommendations
- DOA approval owner replaces hardcoded "Finance Director"

---

## Agent 5: Variance Explanation

**Responsibility**: Explain why actual cash movement differed from a prior forecast. Attribute variance to named drivers. Report residual as Unexplained Variance.

**Type**: LLM-driven (Claude 3.5 Sonnet for driver attribution and narrative) + deterministic (variance arithmetic).

**⚠️ LLM MOCK**: Uses mock template strings in S0–S14. Real API wired in S15.

**Inputs**:
- Actual cash position from Agent 1 (current and historical)
- Prior forecast from Agent 2 (run N-1 outputs)
- `ar_schedule`, `ap_schedule`, `manual_assumptions` tables (for attribution)
- `statement` table (for historical actuals)

**Output shape**:
```json
{
  "run_id": "uuid",
  "variance_period": "2026-08-20",
  "actual_closing_usd": 12840000,
  "forecast_closing_usd": 13180000,
  "total_variance_usd": -340000,
  "variance_direction": "Unfavorable",
  "variance_pct": -2.6,
  "forecast_accuracy_pct": 87.5,
  "accuracy_tolerance_pct": 5.0,
  "drivers": [
    {
      "driver": "Delayed AR — Customer A",
      "amount_usd": -340000,
      "category": "AR",
      "detail": "Expected receipt of $340K on 2026-08-20 not received. Customer A has shown 4–6 day delay pattern in 3 of last 4 months.",
      "one_off_flag": false,
      "one_off_basis": null
    }
  ],
  "unexplained_variance_usd": 0,
  "unexplained_variance_note": null,
  "narrative": "Total unfavorable variance of $340K on 20 Aug 2026. Fully attributed to a delayed AR receipt from Customer A ($340K). This counterparty has shown a recurring 4–6 day collection delay. No unexplained variance."
}
```

**Variance arithmetic**:
```
Total Variance = Actual Closing (N) − Forecast Closing (N)
Variance %     = (Actual − Forecast) / |Forecast| × 100
Variance Direction = Favorable if Total > 0; Unfavorable if Total < 0

Forecast Accuracy (%) =
  Count(days where |Actual − Forecast| < Forecast × 0.05) / Total days × 100
  Tolerance: ±5%
```

**Driver attribution rules**:
1. Identify all AR items due on the variance date that did not arrive → Delayed AR drivers
2. Identify all AP items due that settled early or late → Early/Late AP drivers
3. Identify manual assumptions that did not materialise → Assumption miss drivers
4. Any outflow exceeding 3× the 30-day average → One-off driver flag (Rule B)
5. Sum attributed drivers
6. `unexplained_variance_usd = Total Variance − Sum(driver amounts)`
7. If `unexplained_variance_usd ≠ 0`, add an Unexplained Variance entry — never force to zero

**Forecast Accuracy**: Computed over the active forecast horizon. Reported in Agent output and surfaced on CFO Summary Live Insights panel.

**Changes from v1.0**:
- **Removed**: "drivers must sum to total variance" rule — replaced with Unexplained Variance
- Variance % metric added to output
- Tolerance changed from ±3% to ±5%
- One-off statistical detection (Rule B: 3× 30-day avg) added to driver attribution
- `one_off_flag` and `one_off_basis` fields added to driver objects

---

## Agent 6: CFO Summary

**Responsibility**: Compose the full management-ready daily cash report and the plain-text Daily Briefing narrative.

**Type**: LLM-driven (Claude 3.5 Sonnet for narrative composition).

**⚠️ LLM MOCK**: Uses mock template strings in S0–S14. Real API wired in S15.

**Inputs**: All upstream agent outputs (Agents 1–5, 7, 8).

**Two modes**:

**Report Mode** → `/cfo-summary/report`:
Produces the 7-section executive report:
1. Executive Summary (1-paragraph position narrative)
2. Cash Position (entity table with MTD change — not YTD)
3. Forecast Outlook (7/30/60-day table)
4. Actions Required (Why/What/When/Control list, max 10)
5. Variance Explanation (narrative + drivers)
6. Data Caveats (stale feeds, estimated values)
7. Source References (all data sources with timestamps)

**Briefing Mode** → `/daily-briefing`:
Produces the plain-text ±4-day narrative:
- Behind Us (last 4 days): date + narrative + optional precedent callout from Agent 7
- Ahead of Us (next 4 days): date + narrative + Major Outflow Alert if outflow > 10% of Usable Cash
- If Nothing Changes Outlook: conditional statement

**Daily Briefing must remain prose** — no cards, no metrics, no structured components. This is a non-negotiable product rule.

**Cash Position table (Report Mode)**:
```
Columns: Entity | USD Equivalent | MTD Change | Trend
MTD Change = Current balance − balance on 1st of current month (USD equivalent)
Trend = Up / Flat / Down
```

**Changes from v1.0**:
- Report: YTD Change replaced with MTD Change in Cash Position section
- Briefing: Major Outflow Alert added to "Ahead of Us" entries (>10% of Usable Cash)
- Approval hierarchy and cut-off times in Actions Required now reference DOA and entity-level configs

---

## Agent 7: Treasury Continuity

**Responsibility**: Surface historical precedents from logged decision history to support institutional memory and reduce key-person dependency.

**Type**: Deterministic retrieval + LLM optional (narrative framing).

**Inputs**:
- `recommendation_history` collection (MongoDB): past recommendations, approval status, outcomes
- Current context from Agent 1 and Agent 3 (to identify relevant historical matches)

> **Note**: `decision_log` (PostgreSQL) is deferred to Phase 2. MVP uses MongoDB `recommendations` collection for Agent 7 retrieval. Agent 7 reads from MongoDB only.

**Output shape**:
```json
{
  "run_id": "uuid",
  "precedents": [
    {
      "date": "2026-02-14",
      "situation": "EU Entity EUR balance fell below minimum threshold (€180K shortfall)",
      "action_taken": "Funded €180K from UK Operations Barclays GBP pool",
      "outcome": "Resolved within 2 business days. No AP payment delays.",
      "relevance": "Current EU Entity breach (€70K shortfall) matches this pattern."
    }
  ]
}
```

**Surfaces in**: Daily Briefing "Behind Us" section as optional callout lines. Grows more useful over time as more decisions are logged.

**Changes from v2.0**: Input source clarified — MongoDB `recommendations` collection (not decision_log); decision_log deferred note added.

---

## Agent 8: Policy-aware Control

**Responsibility**: Middleware — validates all Action Recommendation outputs against configured policy before they surface to the user. Blocks policy violations.

**Type**: Deterministic rules engine.

**Inputs**:
- Agent 4 draft recommendations
- `account` table (min_threshold, restricted_flag, od_limit)
- `entity_investment_cutoffs` config
- `doa_policy` config
- `investment_policy` config

**Validation checks**:
1. Does the recommended action respect `min_threshold` for all affected accounts post-action?
2. Does the action involve a `restricted_flag = true` account? If yes → block + explain
3. Does the recommendation have all 4 Why/What/When/Control fields populated? If not → block
4. Is the recommendation language evaluative (not execution-based)? If not → rewrite
5. Is an investment recommendation made without an uploaded investment SOP? If yes → downgrade to surplus-flag-only
6. Does the approval owner reference the DOA policy correctly?

**Output**: Pass / Block + reason for each recommendation. Blocked items are not surfaced to the user. Reason is logged.

**No changes from v1.0.**

---

## Open Agent Decisions

| # | Decision | Status |
|---|---|---|
| **1** | Opening balance anchor rule for Agent 2 | OPEN — parked; do not build Agent 2 forecast calculation until resolved |
| **2** | Investment cut-off time values for Agent 4 | OPEN — awaiting amit j input |
| **3** | Investment policy document for Agent 4 | OPEN — awaiting amit j draft |
| **4** | PDF parser integration into Agent 1 data pipeline | OPEN — awaiting sample files |
| **5** | LangGraph orchestration: sequential vs. parallel | Recommendation: sequential for MVP; parallelise Agents 2+3 in Phase 2 |
| **6** | LLM model selection per agent | Recommendation: Claude 3.5 Sonnet for Agents 4, 5, 6; no LLM for Agents 1, 3, 7, 8 |
| **7** | Caching strategy for agent outputs | Recommendation: cache Agent 1 output for 1 hour; invalidate on new file ingestion |

---

## Agent Run Traceability

Every agent run produces:
- `run_id` (UUID): unique identifier for this run
- `triggered_by`: what caused this run (scheduled / user-action / upstream-agent)
- `as_of`: timestamp of the data this run used
- `agent_version`: version string of the agent logic

All recommendation outputs reference their `run_id`. All approval actions reference the `recommendation_id` and `run_id`.

## LLM vs. Deterministic Boundary

| Agent | Core Logic | LLM Role | Build Sessions |
|---|---|---|---|
| 1 — Daily Cash Position | Deterministic | None | S3 |
| 2 — Forecast Intelligence | Deterministic | Optional: narrative explanation | S7/S14 (BLOCKED) |
| 3 — Liquidity Risk | Deterministic | Optional: narrative risk summary | S4 |
| 4 — Action Recommendation | LLM | Recommendation drafting, Why/What rationale | S6 (mocked S6, real S15) |
| 5 — Variance Explanation | Deterministic arithmetic + LLM | Driver attribution narrative | S10 (mocked, real S15) |
| 6 — CFO Summary | LLM | Full narrative composition (report + briefing) | S9 (mocked, real S15) |
| 7 — Treasury Continuity | Deterministic retrieval | Optional: precedent narrative framing | S9 |
| 8 — Policy-aware Control | Deterministic rules | None | S6 |