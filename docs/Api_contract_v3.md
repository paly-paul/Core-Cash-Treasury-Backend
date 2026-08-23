# Core Cash — API Contract

**Version**: 3.0
**Date**: 22 August 2026
**Status**: Ready for backend implementation
**Supersedes**: v2.0 (21 August 2026)
**Audience**: Backend engineers (App Backend + AI Backend), Frontend engineers

---

## What Changed in v3.0

| Area | v2.0 | v3.0 | Rationale |
|---|---|---|---|
| **Architecture** | Single-service assumption in handoff | Dual-service (App Backend + AI Backend) from day one | MVP builds both services with SQS from the start |
| **Forecast endpoint** | Sync `GET /forecast?horizon=7` (503 stub) | Async `POST /api/forecast/request` → poll `GET /api/forecast/{id}` | Consistent async pattern; latency acceptable |
| **Recommendation endpoint** | `GET /recommendations/active` (sync list) | Async `POST /api/recommendations/request` → poll `GET /api/recommendations/{id}` | Consistent with forecast; aligns with SQS job pattern |
| **Chat endpoint** | `/chat/stream` on App Backend | `/ai/chat/stream` on AI Backend | SSE chat is an AI Backend responsibility per architecture |
| **Account schema** | Missing `refresh_frequency`, `include_in_cash_position`, `od_headroom` | All three added | Required by Agent 1 confidence logic and cash position calculation |
| **Trends / Predictions** | `/api/trends/patterns` | `/trends/predictions` (Phase 2, deferred) | Naming aligned; deferred confirmed |
| **Variance tolerance** | ±3% reference in some docs | ±5% everywhere | Confirmed decision |
| **LLM wiring** | Unclear boundary | Agents 4, 5, 6 use mock in build sessions; `.env` placeholder for `ANTHROPIC_API_KEY` | Wire real API in a dedicated session post Step-8 review |
| **Shared lib schemas** | Described in architecture docs only | SQS job envelope schemas referenced in contract | Shared lib is built first; both services depend on it |

---

## Base URLs

```
App Backend:  https://api.{customer}.core-cash.com
AI Backend:   https://ai.{customer}.core-cash.com
```

All standard treasury endpoints (`/api/*`, `/auth/*`, `/health`) are served by the **App Backend**.
Only two endpoints are served by the **AI Backend**: `/ai/chat/stream` and `/health` (AI Backend health).

---

## Foundational Decisions

| Parameter | Decision |
|---|---|
| Transport | REST + JSON (App Backend); SSE (AI Backend chat only) |
| Auth | JWT in HTTP-only cookies (set on login, cleared on logout); validated by both services using shared Cognito public key |
| Async jobs | `POST` to request → 202 with `{request_id, status: "queued"}` → poll GET until `completed` or `failed` |
| Poll interval | Frontend polls every 5 seconds until terminal status |
| Chat | Server-Sent Events (SSE) on AI Backend only |
| Errors | Standard error envelope (see Error Contract below) |
| Timestamps | ISO 8601 UTC throughout |
| Monetary amounts | USD equivalent unless field name indicates local currency (`_local` suffix) |
| Thresholds | 70% warning globally (never 80%) |
| Confidence | Two-step for bank feeds (24h/48h); 7-day threshold for manual-upload feeds |
| Variance tolerance | ±5% (never ±3%) |
| LLM | Agents 4, 5, 6 — mock in build sessions; `ANTHROPIC_API_KEY` placeholder in `.env`; wire real API post Step-8 sign-off |

---

## Shared Library Job Envelope Schemas

Both services import from `core-cash-shared`. The SQS job envelope is the inter-service contract.

### SQSJobMessage (published by App Backend, consumed by AI Backend)

```json
{
  "job_id": "rec_20260822_093000_a1b2c3d4",
  "job_type": "recommendation | forecast | cfo_summary | variance",
  "client_id": "uuid",
  "payload": {
    "cash_position_date": "2026-08-22",
    "policy_id": "policy_default",
    "horizon_days": 7
  },
  "published_at": "2026-08-22T09:30:00Z",
  "correlation_id": "optional-trace-id"
}
```

### SQSJobResult (written to MongoDB by AI Backend; polled via App Backend)

```json
{
  "job_id": "rec_20260822_093000_a1b2c3d4",
  "status": "pending | running | completed | failed",
  "result": {},
  "error": null,
  "completed_at": "2026-08-22T09:31:05Z"
}
```

---

## Error Contract

All errors return:
```json
{
  "error": {
    "code": "STALE_FX_RATE",
    "message": "Today's FX rate has not been entered. Using prior day's rate (2026-08-20). Figures may not reflect current exchange rates.",
    "severity": "warning | error",
    "details": {}
  }
}
```

| Code | HTTP Status | Description |
|---|---|---|
| `UNAUTHORIZED` | 401 | JWT missing or expired |
| `FORBIDDEN` | 403 | User lacks permission for this resource |
| `NOT_FOUND` | 404 | Resource does not exist |
| `VALIDATION_ERROR` | 422 | Request body fails validation |
| `STALE_FX_RATE` | 200 (warning) | Today's FX rate not entered; prior day used |
| `FEED_MISSING` | 200 (warning) | One or more expected bank feeds not received |
| `AGENT_ERROR` | 500 | Agent failed to produce output |
| `JOB_QUEUED` | 202 | Async job accepted; poll for result |
| `OPENING_BALANCE_UNRESOLVED` | 503 | Forecast blocked — opening balance anchor rule not yet confirmed |

---

## AUTH ENDPOINTS (App Backend)

### POST /auth/login
```json
Request:
{ "email": "user@company.com", "password": "..." }

Response 200:
{ "user": { "id": "uuid", "name": "Jane Smith", "role": "TreasuryManager", "entity_id": "uuid" } }
```
JWT set in HTTP-only cookie. Role values: `Viewer | Analyst | TreasuryManager | CFO`.

### POST /auth/logout
Clears JWT cookie. Returns `204 No Content`.

### POST /auth/refresh
Exchanges refresh token for new JWT. JWT set in HTTP-only cookie.
```json
Response 200:
{ "message": "Token refreshed" }
```

### GET /auth/me
```json
Response 200:
{ "id": "uuid", "name": "Jane Smith", "email": "user@company.com", "role": "TreasuryManager", "entity_id": "uuid" }
```

---

## CASH POSITION ENDPOINTS (App Backend)

### GET /api/cash-position/current

Returns Daily Cash Position Agent output (Agent 1). Synchronous — queried directly from PostgreSQL with in-process 1-hour cache. Cache invalidated on new file upload.

```json
Response 200:
{
  "run_id": "uuid",
  "as_of": "2026-08-22T09:00:00Z",
  "fx_rates_date": "2026-08-22",
  "fx_rates_warning": false,
  "total_cash_usd": 12840000,
  "available_cash_usd": 12840000,
  "restricted_cash_usd": 3400000,
  "usable_cash_usd": 9440000,
  "od_limit_total_usd": 2000000,
  "data_confidence": "High",
  "stale_feeds": [
    { "account_name": "Barclays GBP Ops", "hours_stale": 51, "confidence": "Low" }
  ],
  "missing_feeds": [],
  "entities": [
    {
      "entity_id": "uuid",
      "entity_name": "US HQ",
      "base_currency": "USD",
      "closing_balance_local": 7200000,
      "available_balance_local": 7200000,
      "restricted_balance_local": 0,
      "od_limit_local": null,
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
          "refresh_frequency": "Daily",
          "include_in_cash_position": true,
          "status": "Green",
          "confidence": "High",
          "statement_date": "2026-08-21",
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

**Field rules:**
- `available_balance` — bank-reported available balance (after uncleared items). Always separate from `closing_balance`.
- `od_limit` — nullable. If set and `closing_balance < 0`: `od_utilised = true`, `od_headroom = od_limit − abs(closing_balance)`.
- `od_limit_total_usd` — sum of od_limits across all accounts with OD facility. Never added to `usable_cash_usd`.
- `usable_cash_usd` = `available_cash_usd` − `restricted_cash_usd`. OD headroom is separate.
- `status` per account — Green: available ≥ threshold; Yellow: available ≥ threshold × 0.70; Red: available < threshold × 0.70.
- `fx_rates_warning: true` when prior day's rate is used. Propagates to all USD-equivalent figures.
- `active_breaches` column order: entity_name → account_name → min_threshold → current_balance → shortfall → currency.

### GET /api/cash-position/by-entity/{entity_id}
Same shape as `/current` but filtered to one entity.

### GET /api/cash-position/by-date/{date}
Historical position for a specific date (YYYY-MM-DD). Same shape. No cache.

---

## ACCOUNT MASTER ENDPOINTS (App Backend)

### GET /api/accounts
```json
Response 200:
{
  "accounts": [
    {
      "id": "uuid",
      "account_number": "ACC-001",
      "account_name": "JPM USD Main",
      "bank": "JPMorgan",
      "entity_id": "uuid",
      "entity_name": "US HQ",
      "currency": "USD",
      "restricted_flag": false,
      "min_threshold": 2000000,
      "od_limit": null,
      "refresh_frequency": "Daily",
      "include_in_cash_position": true,
      "status": "Active"
    }
  ]
}
```

### POST /api/accounts
Creates a new account.
```json
Request:
{
  "account_number": "ACC-007",
  "account_name": "Citi EUR Reserve",
  "bank_id": "uuid",
  "entity_id": "uuid",
  "currency": "EUR",
  "restricted_flag": false,
  "min_threshold": 300000,
  "od_limit": null,
  "refresh_frequency": "Daily",
  "include_in_cash_position": true
}

Response 201: { ...full account object... }
```
Validation: `account_number` unique per bank + client; `min_threshold ≥ 0`; `od_limit ≥ 0` if set; `currency` in [USD, GBP, EUR]; `entity_id` exists; `refresh_frequency` in [Daily, Manual].

### PUT /api/accounts/{id}
Updates an account. All fields editable except `account_number`.
```json
Response 200: { ...updated account object... }
```

### DELETE /api/accounts/{id}
Soft-delete. Sets `include_in_cash_position = false`. Data retained. Audit log entry created.
```json
Response 200: { "status": "deactivated" }
```

### POST /api/accounts/bulk-import
Accepts CSV. Creates or updates accounts by `account_number`.
```json
Response 202:
{
  "rows_received": 10,
  "rows_created": 8,
  "rows_updated": 2,
  "rows_failed": 0
}
```

---

## FORECAST ENDPOINTS (App Backend — Async)

Forecast jobs are processed by the AI Backend (Agent 2). App Backend publishes the job to SQS; AI Backend runs the agent and writes the result to MongoDB; App Backend polls MongoDB for the result.

**⚠️ FORECAST CALCULATION BLOCKED** — Opening balance anchor rule is unresolved. Forecast endpoints are built (scaffold + 503 stub for the calculation result). Pre-work endpoints (assumptions CRUD) are live.

### POST /api/forecast/request
Publishes a forecast job to SQS. Returns immediately.

```json
Request:
{
  "horizon_days": 7,
  "cash_position_date": "2026-08-22",
  "policy_id": "policy_default"
}

Response 202:
{
  "forecast_id": "fct_20260822_093000_b2c3d4e5",
  "status": "queued",
  "queued_at": "2026-08-22T09:30:00Z",
  "horizon_days": 7
}
```

### GET /api/forecast/{forecast_id}
Poll for forecast result. Frontend polls every 5 seconds.

```json
Response 200 (pending):
{
  "forecast_id": "fct_20260822_093000_b2c3d4e5",
  "status": "pending | running",
  "queued_at": "2026-08-22T09:30:00Z"
}

Response 200 (completed):
{
  "forecast_id": "fct_20260822_093000_b2c3d4e5",
  "status": "completed",
  "run_id": "uuid",
  "triggered_by": "user_request | ap_upload | assumption_change",
  "as_of": "2026-08-22T09:00:00Z",
  "opening_balance_date": "2026-08-21",
  "opening_cash_usd": 12840000,
  "horizons": [
    {
      "horizon_days": 7,
      "expected_inflows_usd": 2100000,
      "expected_outflows_usd": 1800000,
      "forecast_closing_usd": 13140000,
      "daily_positions": [
        {
          "date": "2026-08-23",
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

Response 200 (failed):
{
  "forecast_id": "fct_20260822_093000_b2c3d4e5",
  "status": "failed",
  "error": "OPENING_BALANCE_UNRESOLVED"
}
```

**Significant outflow flag**: any single-day outflow > 10% of Usable Cash.
**Forecast re-trigger**: on AP file upload and on any manual assumption create/update/delete. Does NOT re-trigger on AR upload or daily bank statement ingestion.
**Assumption filter**: only `manual_assumptions` with `confidence_pct >= 50` included. Threshold from `system_config.forecast_confidence_threshold`.

### GET /api/forecast/current
Returns the latest completed forecast for the client. Same shape as `GET /api/forecast/{id}` completed response.

### GET /api/forecast/variance
Returns variance explanation for the most recent completed variance run. See VARIANCE ENDPOINTS below.

### GET /api/forecast/assumptions
```json
Response 200:
{
  "assumptions": [
    {
      "id": "uuid",
      "entity_id": "uuid",
      "entity_name": "US HQ",
      "currency": "USD",
      "direction": "Outflow",
      "amount": 2000000,
      "date": "2026-09-15",
      "category": "Capex",
      "description": "New office fit-out payment",
      "confidence_pct": 75,
      "included_in_forecast": true,
      "created_by": "uuid",
      "created_at": "2026-08-22T10:00:00Z",
      "updated_at": "2026-08-22T10:00:00Z"
    }
  ]
}
```
`included_in_forecast` is system-derived (`confidence_pct >= 50`). Not user-settable.

### POST /api/forecast/assumptions
```json
Request:
{
  "entity_id": "uuid",
  "currency": "USD",
  "direction": "Outflow",
  "amount": 2000000,
  "date": "2026-09-15",
  "category": "Capex",
  "description": "New office fit-out payment",
  "confidence_pct": 75
}

Response 201: { ...full assumption object... }
```
Validation: `direction` in [Inflow, Outflow]; `amount > 0`; `date >= today`; `category` in [Payroll, Tax, Investment, Loan Repayment, Capex, Operating, Other]; `confidence_pct` 0–100.
Triggers forecast re-run on success.

### PUT /api/forecast/assumptions/{id}
Updates assumption. Triggers forecast re-run. Audit log entry created.

### DELETE /api/forecast/assumptions/{id}
Soft-deletes assumption. Triggers forecast re-run. Audit log entry created.

---

## LIQUIDITY RISK ENDPOINTS (App Backend)

Liquidity risk is computed by Agent 3 (AI Backend). Result is written to MongoDB. App Backend reads and serves.
This endpoint is synchronous on the read path — returns the latest completed risk assessment from MongoDB.

### GET /api/liquidity-risk/current

```json
Response 200:
{
  "run_id": "uuid",
  "as_of": "2026-08-22T09:00:00Z",
  "risk_score": 6,
  "risk_level": "Medium",
  "score_breakdown": {
    "base": 1,
    "breach_points": 2,
    "stale_feed_points": 1,
    "ar_concentration_points": 1,
    "shortfall_points": 0,
    "raw_total": 5,
    "capped": false
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
  "forecast_shortfall_days": ["2026-08-25"],
  "ar_concentration_risk": {
    "top_3_share_pct": 69.0,
    "threshold_pct": 70.0,
    "breached": false,
    "high_single_counterparty": false,
    "top_counterparties": [
      { "name": "Customer A", "share_pct": 34.0 },
      { "name": "GlobalTech Ltd", "share_pct": 21.0 },
      { "name": "Nordic AS", "share_pct": 14.0 }
    ]
  },
  "stale_feeds": [
    { "account_name": "Barclays GBP Ops", "hours_stale": 51, "confidence": "Low" }
  ],
  "narrative": "Liquidity risk is Medium. One active breach in EU Entity (€70K shortfall). AR concentration below 70% threshold. One stale feed (Barclays GBP)."
}
```

**Score calculation:**
```
Base            = 1
Breach          = +2 per active breach of min_threshold, capped at 6 (3+ breaches = max 6 from this component)
Stale feed      = +1 if any bank feed > 48h stale
AR concentration= +1 if top 3 counterparties > 70% of total AR outstanding
Shortfall       = +2 if any day in 7-day forecast has projected usable cash < min_threshold
                  (use 0 until Forecast Agent unblocked; TODO comment in code)
Raw total capped at 10.

Scale: 1–3 = Low (Green), 4–6 = Medium (Yellow), 7–10 = High (Red)
```

**AR Concentration Risk:**
- Concentration % = Sum(AR outstanding, top 3 counterparties) / Total AR outstanding × 100
- `high_single_counterparty = true` if any single counterparty > 40% of total AR
- Label in code and output must be `ar_concentration_risk` — not `concentration_risk`
- AR only — never includes AP or cash balances in this calculation

### GET /api/liquidity-risk/alerts
Returns only Critical + High severity items from the current risk assessment.
```json
Response 200:
{
  "as_of": "2026-08-22T09:00:00Z",
  "risk_level": "High",
  "critical_breaches": [...],
  "forecast_shortfall_days": [...]
}
```

---

## RECOMMENDATIONS ENDPOINTS (App Backend — Async)

Recommendation jobs are processed by Agent 4 (AI Backend) via the 8-agent LangGraph chain. App Backend publishes the job; AI Backend processes it and writes to MongoDB; App Backend polls for result.

### POST /api/recommendations/request
```json
Request:
{
  "cash_position_date": "2026-08-22",
  "policy_id": "policy_default"
}

Response 202:
{
  "request_id": "rec_20260822_093000_a1b2c3d4",
  "status": "queued",
  "queued_at": "2026-08-22T09:30:00Z",
  "estimated_completion": "30–60 seconds"
}
```
Role gate: Analyst, TreasuryManager, CFO only.

### GET /api/recommendations/{request_id}
Poll for recommendation result. Frontend polls every 5 seconds.

```json
Response 200 (pending / running):
{
  "request_id": "rec_20260822_093000_a1b2c3d4",
  "status": "pending | running",
  "queued_at": "2026-08-22T09:30:00Z"
}

Response 200 (completed):
{
  "request_id": "rec_20260822_093000_a1b2c3d4",
  "status": "completed",
  "run_id": "uuid",
  "generated_at": "2026-08-22T09:31:05Z",
  "recommendation_count": 2,
  "recommendations": [
    {
      "id": "uuid",
      "priority": 1,
      "type": "Funding",
      "why": "EU Entity EUR balance is €70K below the €500K minimum threshold. €120K AP run due Monday 25 Aug will widen the shortfall to €190K without action.",
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
  ],
  "reasoning_trace": [
    { "step": 1, "agent": "daily_cash", "status": "complete", "duration_ms": 220 },
    { "step": 2, "agent": "liquidity_risk", "status": "complete", "duration_ms": 180 },
    { "step": 3, "agent": "forecast", "status": "complete", "duration_ms": 2100 },
    { "step": 4, "agent": "policy_check", "status": "complete", "duration_ms": 95 },
    { "step": 5, "agent": "recommendation", "status": "complete", "duration_ms": 9200 }
  ]
}

Response 200 (failed):
{
  "request_id": "rec_20260822_093000_a1b2c3d4",
  "status": "failed",
  "error": "Agent processing failed. Please retry."
}
```

**Recommendation rules:**
- Maximum 10 items per run. Priority: breach > shortfall > surplus investment.
- All `why`, `what`, `when`, `control` fields required and non-null on every item. Agent 8 blocks any item failing this.
- `what` field language: Evaluate / Consider / Review / Propose / Escalate. Never: Transfer / Execute / Send / Move / Initiate.
- Investment recommendations only appear if `investment_policy` is uploaded for that entity. Otherwise, return surplus-flag-only message in `what`.
- All start `approval_status: Pending`. No auto-approval.

### GET /api/recommendations
List all recommendations for the client (paginated, filterable by status).
```json
Response 200:
{
  "recommendations": [
    {
      "request_id": "rec_20260822_093000_a1b2c3d4",
      "status": "completed",
      "generated_at": "2026-08-22T09:31:05Z",
      "recommendation_count": 2,
      "approval_status": "Pending"
    }
  ],
  "total": 12,
  "page": 1,
  "page_size": 20
}
```

### POST /api/recommendations/{id}/approve
Role gate: TreasuryManager, CFO only.
```json
Request: { "notes": "Approved — instructed bank at 13:45 EST" }
Response 200: { "approval_status": "Approved", "approved_by": "uuid", "approved_at": "2026-08-22T13:45:00Z" }
```

### POST /api/recommendations/{id}/reject
Role gate: TreasuryManager, CFO only.
```json
Request: { "reason": "Not actioning — will monitor tomorrow" }
Response 200: { "approval_status": "Rejected" }
```

### POST /api/recommendations/{id}/override
Role gate: TreasuryManager, CFO only. Records a manual override action.
```json
Request: { "action_taken": "Manually initiated transfer via bank portal", "notes": "Overriding AI recommendation with different amount" }
Response 200: { "approval_status": "Overridden", "overridden_by": "uuid", "overridden_at": "..." }
```

---

## VARIANCE EXPLANATION ENDPOINTS (App Backend — Async)

Variance jobs are processed by Agent 5 (AI Backend). Blocked until Forecast Agent (Agent 2) is unblocked.

### POST /api/forecast/variance/request
```json
Request:
{
  "variance_date": "2026-08-21",
  "forecast_id": "fct_20260821_070000_xyz"
}

Response 202:
{
  "variance_id": "var_20260822_093000_c3d4e5f6",
  "status": "queued",
  "queued_at": "2026-08-22T09:30:00Z"
}
```

### GET /api/forecast/variance/{variance_id}
Poll for variance result.

```json
Response 200 (completed):
{
  "variance_id": "var_20260822_093000_c3d4e5f6",
  "status": "completed",
  "run_id": "uuid",
  "variance_period": "2026-08-21",
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
      "detail": "Expected $340K receipt on 2026-08-21 not received. Recurring 4–6 day delay pattern.",
      "one_off_flag": false,
      "one_off_basis": null
    }
  ],
  "unexplained_variance_usd": 0,
  "unexplained_variance_note": null,
  "narrative": "Total unfavorable variance of $340K on 21 Aug 2026. Fully attributed to a delayed AR receipt from Customer A."
}
```

**Variance rules:**
- `total_variance = actual_closing − forecast_closing`
- `variance_pct = (actual − forecast) / |forecast| × 100`
- `forecast_accuracy_pct` — tolerance ±5% (never ±3%)
- `unexplained_variance_usd` is always present. Never forced to zero. If > 0, `unexplained_variance_note` explains what could not be attributed and recommends manual investigation.
- Drivers never forced to sum to total. Residual = Unexplained Variance.
- `one_off_flag: true` when outflow > 3× 30-day average daily outflow (statistical Rule B).

### GET /api/forecast/variance/current
Returns the latest completed variance explanation. Same shape as completed poll response.

---

## CFO SUMMARY ENDPOINTS (App Backend — Async for generation, Sync for read)

CFO Summary is composed by Agent 6 (AI Backend). Stored in MongoDB. Triggered on demand or by morning schedule via SQS.

### POST /api/cfo-summary/request
```json
Response 202:
{
  "summary_id": "cfo_20260822_070000_d4e5f6g7",
  "status": "queued",
  "queued_at": "2026-08-22T07:00:00Z"
}
```

### GET /api/cfo-summary/latest
Returns the most recent completed CFO Summary. Synchronous read from MongoDB.

```json
Response 200:
{
  "summary_id": "cfo_20260822_070000_d4e5f6g7",
  "run_id": "uuid",
  "report_date": "2026-08-22",
  "overall_confidence": "High",
  "cover": {
    "title": "Daily Cash Report – 22 August 2026",
    "total_cash_usd": 12840000,
    "usable_cash_usd": 9440000,
    "od_limit_total_usd": 2000000,
    "forecast_closing_7d_usd": 13140000,
    "status": "Attention"
  },
  "executive_summary": "Cash position is Attention at $9.4M usable cash...",
  "cash_position": [
    {
      "entity_name": "US HQ",
      "usable_cash_usd": 7200000,
      "mtd_change_usd": 340000,
      "trend": "Up"
    }
  ],
  "forecast_outlook": [
    {
      "horizon": "7 Day",
      "opening_usd": 12840000,
      "inflows_usd": 2100000,
      "outflows_usd": 1800000,
      "closing_usd": 13140000,
      "risk": "Green"
    },
    { "horizon": "30 Day", "opening_usd": 13140000, "inflows_usd": 5800000, "outflows_usd": 5200000, "closing_usd": 13740000, "risk": "Green" },
    { "horizon": "60 Day", "opening_usd": 13740000, "inflows_usd": 11200000, "outflows_usd": 10900000, "closing_usd": 14040000, "risk": "Yellow" }
  ],
  "actions_required": [ "...recommendations array, max 10, same shape as /recommendations/{id} items..." ],
  "variance_explanation": { "...same shape as variance completed response..." },
  "data_caveats": ["Barclays GBP feed is 2 days stale — GBP position confidence: Low"],
  "source_references": [
    {
      "source": "Bank Balances (CSV)",
      "file_name": "bank_balances_21aug.csv",
      "timestamp": "2026-08-21T09:02:00Z",
      "status": "Current"
    }
  ]
}
```

**Field rules:**
- `mtd_change_usd` = current balance − balance on 1st of current month (USD). YTD is removed.
- `od_limit_total_usd` shown in cover separately from `usable_cash_usd`. Never combined.
- `actions_required` max 10 items. Same Why/What/When/Control shape as recommendations.

### GET /api/cfo-summary/live-insights
Polled by frontend every 60 minutes (or on `Refresh Now` trigger).

```json
Response 200:
{
  "as_of": "2026-08-22T09:00:00Z",
  "cash_runway_days": 42,
  "cash_runway_note": "Excludes 2026-08-15 one-off outflow of $1.2M (CAPEX)",
  "liquidity_risk_score": 6,
  "variance_pct": -2.6,
  "forecast_accuracy_pct": 87.5,
  "trend_7d": [
    { "date": "2026-08-15", "cash_runway_days": 44, "risk_score": 5 },
    { "date": "2026-08-16", "cash_runway_days": 43, "risk_score": 5 }
  ]
}
```

**Cash Runway calculation:**
- Historical daily avg = sum of last 30 days actual outflows ÷ 30, excluding one-offs (outflow > 10% of usable_cash)
- Projected daily avg = sum of next 30 days forecast outflows ÷ 30
- Blended avg = (historical + projected) ÷ 2
- `cash_runway_days = usable_cash ÷ blended_avg`
- `cash_runway_note` populated when one-offs were excluded

### GET /api/cfo-summary/export
```json
Request params: ?format=pdf|email|print

Response 200:
{
  "export_id": "uuid",
  "format": "pdf",
  "download_url": "https://s3.../cfo-summary-20260822.pdf",
  "expires_at": "2026-08-22T11:00:00Z"
}
```

---

## DAILY BRIEFING ENDPOINT (App Backend)

### GET /api/daily-briefing/latest
Returns the most recent Daily Briefing from MongoDB (generated by Agent 6, Briefing Mode).

```json
Response 200:
{
  "run_id": "uuid",
  "generated_at": "2026-08-22T07:10:00Z",
  "behind_us": [
    {
      "date": "2026-08-18",
      "date_label": "Mon 18 Aug",
      "narrative": "Cash position opened the week at $12.1M, broadly in line with plan. UK Operations received the expected £420K rent inflow on schedule.",
      "precedent_callout": null
    },
    {
      "date": "2026-08-21",
      "date_label": "Thu 21 Aug",
      "narrative": "EU Entity balance fell to €430K, €70K below the €500K minimum. Customer A $340K receipt delayed — consistent with a recurring 4–6 day pattern.",
      "precedent_callout": "Last time EU Entity was below minimum (Feb 2026), the team funded €180K from UK Operations — resolved in 2 business days."
    }
  ],
  "ahead_of_us": [
    {
      "date": "2026-08-22",
      "date_label": "Fri 22 Aug",
      "narrative": "EU Entity funding action required by 14:00 EST to cover the €120K AP run on Monday.",
      "major_outflow_alert": null
    },
    {
      "date": "2026-08-25",
      "date_label": "Mon 25 Aug",
      "narrative": "Q3 tax payment due in US HQ — $1.2M outflow. Usable cash remains above minimum post-payment.",
      "major_outflow_alert": {
        "category": "Tax",
        "amount_usd": 1200000,
        "pct_of_usable_cash": 12.7,
        "entity": "US HQ",
        "action": "Monitor — no approval action required unless cash position changes."
      }
    }
  ],
  "if_nothing_changes": "If the EUR funding completes today and Customer A's payment arrives within its typical 4-day delay window, cash position should remain in Normal range through end of next week."
}
```

**Rules:**
- `major_outflow_alert` fires when any outflow in next 4 days > 10% of Usable Cash. Requires Forecast Agent; returns null until Agent 2 unblocked.
- `precedent_callout` from Agent 7 (Treasury Continuity). Returns null if no relevant precedent in `recommendation_history`.
- Response is always prose-driven. No metrics cards, no status badges, no structured metric objects. Non-negotiable product rule.

---

## UPLOADS ENDPOINTS (App Backend)

### POST /api/files/upload (bank balances)
Accepts: CSV (primary), BAI2, camt.053, MT940. PDF: future (pending sample file review).

```json
Request: multipart/form-data
  file: <binary>
  file_type: "csv | bai2 | camt053 | mt940"
  column_mapping: { "date": "Date", "amount": "Amount", "debit_credit": "D/C" }  // CSV only

Response 202:
{
  "upload_id": "uuid",
  "file_name": "bank_balances_22aug.csv",
  "status": "Processing",
  "rows_received": 6,
  "rows_valid": 5,
  "rows_flagged": 1,
  "flagged_rows": [
    {
      "row": 4,
      "issue": "Unmapped account — Account Number 'ACC-9921' not in Account Master",
      "action": "Included with Low confidence; map in Account Master to resolve"
    }
  ],
  "negative_balances_detected": 1,
  "negative_balance_accounts": ["BofA EUR Reserve — treated as OD utilisation"]
}
```

### POST /api/files/upload/ar
Accepts: CSV.
```json
Response 202: { "upload_id": "uuid", "status": "Processing", "rows_received": 20, "rows_valid": 20, "rows_flagged": 0 }
```

### POST /api/files/upload/ap
Accepts: CSV. Triggers forecast re-run on success (publishes SQS job).
Same response shape as AR.

### GET /api/files
List upload history (paginated).
```json
Response 200:
{
  "uploads": [
    {
      "upload_id": "uuid",
      "file_name": "bank_balances_22aug.csv",
      "file_type": "csv",
      "upload_type": "bank_balances | ar | ap",
      "status": "Completed | Processing | Failed",
      "rows_processed": 6,
      "rows_valid": 5,
      "uploaded_by": "Jane Smith",
      "uploaded_at": "2026-08-22T09:02:00Z",
      "parsed_at": "2026-08-22T09:02:15Z"
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

### GET /api/files/{id}/status
Returns current parse status for a specific upload.

### DELETE /api/files/{id}
Soft-delete upload record. Underlying data retained in PostgreSQL. Audit log entry created.

---

## FX RATES ENDPOINTS (App Backend)

### GET /api/config/fx-rates
```json
Response 200:
{
  "today_entered": true,
  "warning": false,
  "rates": [
    {
      "currency_from": "GBP",
      "currency_to": "USD",
      "rate": 1.27,
      "rate_date": "2026-08-22",
      "entered_by": "Jane Smith",
      "entered_at": "2026-08-22T09:02:00Z"
    },
    {
      "currency_from": "EUR",
      "currency_to": "USD",
      "rate": 1.09,
      "rate_date": "2026-08-22",
      "entered_by": "Jane Smith",
      "entered_at": "2026-08-22T09:02:00Z"
    }
  ],
  "prior_rates": [ "...last 7 days of entries..." ]
}
```

### POST /api/config/fx-rates
Admin only (1 designated user per client entity).
```json
Request:
{
  "rates": [
    { "currency_from": "GBP", "rate": 1.27 },
    { "currency_from": "EUR", "rate": 1.09 }
  ]
}

Response 201:
{ "rate_date": "2026-08-22", "rates_entered": 2, "warning_cleared": true }
```

---

## INVESTMENT POLICY ENDPOINTS (App Backend)

### GET /api/config/investment-policy
```json
Response 200 (policy uploaded):
{
  "policy_id": "uuid",
  "entity_id": "uuid",
  "entity_name": "US HQ",
  "version": "v2",
  "document_url": "https://s3.../investment-policy-v2.pdf",
  "uploaded_by": "Jane Smith",
  "uploaded_at": "2026-01-15T10:00:00Z",
  "is_active": true
}

Response 200 (no policy):
{ "policy": null }
```
When `policy: null`, investment recommendations are suppressed — surplus-flag-only mode.

### POST /api/config/investment-policy
Admin only. Uploads new investment policy document. Prior version deactivated automatically.
```json
Request: multipart/form-data: file + entity_id + version
Response 201: { ...full policy object... }
```

### GET /api/config/investment-cutoffs
```json
Response 200:
{
  "cutoffs": [
    {
      "entity_id": "uuid",
      "entity_name": "US HQ",
      "cutoff_time": "16:00",
      "timezone": "America/New_York",
      "investment_account_id": "uuid",
      "investment_account_name": "JPM USD Main"
    }
  ]
}
```

### PUT /api/config/investment-cutoffs/{entity_id}
Admin only. Updates cut-off time and investment account for an entity.

---

## AUDIT LOG ENDPOINTS (App Backend)

### GET /api/audit-log
Queryable by date, user, entity, action. Role gate: TreasuryManager, CFO.
```json
Response 200:
{
  "entries": [
    {
      "id": "uuid",
      "client_id": "uuid",
      "user_id": "uuid",
      "user_name": "Jane Smith",
      "action": "recommendation_approved",
      "entity_type": "recommendation",
      "entity_id": "rec_20260822_093000_a1b2c3d4",
      "old_value": { "approval_status": "Pending" },
      "new_value": { "approval_status": "Approved" },
      "ip_address": "203.0.113.4",
      "created_at": "2026-08-22T13:45:00Z"
    }
  ],
  "total": 1284,
  "page": 1,
  "page_size": 50
}
```

### GET /api/audit-log/export
```json
Request params: ?format=csv|pdf&date_from=2026-08-01&date_to=2026-08-22

Response 200:
{
  "export_id": "uuid",
  "format": "csv",
  "download_url": "https://s3.../audit-log-export.csv",
  "expires_at": "2026-08-22T11:00:00Z"
}
```

---

## METADATA ENDPOINTS (App Backend)

### GET /api/metadata/entities
```json
Response 200:
{
  "entities": [
    { "id": "uuid", "name": "US HQ", "base_currency": "USD" },
    { "id": "uuid", "name": "UK Operations", "base_currency": "GBP" },
    { "id": "uuid", "name": "EU Entity", "base_currency": "EUR" }
  ]
}
```

### GET /api/metadata/currencies
```json
Response 200:
{ "currencies": ["USD", "GBP", "EUR"] }
```

---

## HEALTH ENDPOINTS

### GET /health (App Backend)
```json
Response 200:
{ "status": "ok", "service": "app-backend", "db": "connected", "mongo": "connected", "sqs": "connected", "version": "3.0.0" }
```

### GET /health (AI Backend — at https://ai.{customer}.core-cash.com/health)
```json
Response 200:
{ "status": "ok", "service": "ai-backend", "mongo": "connected", "sqs": "connected", "postgres_readonly": "connected", "version": "3.0.0" }
```

---

## CHAT ENDPOINT (AI Backend — SSE)

**Base URL**: `https://ai.{customer}.core-cash.com`

### GET /ai/chat/stream
Server-Sent Events streaming. Authenticated via same Cognito JWT (HTTP-only cookie or `Authorization: Bearer` header).

Chat handler queries the **latest agent outputs from MongoDB only** — it does not invoke a new agent run. It composes a natural language response from cached agent data and streams tokens.

**Routing logic (MVP):**
- Balance / position questions → retrieves Agent 1 output
- Risk / shortfall questions → retrieves Agent 3 + Agent 2 outputs
- Recommendation explanations → retrieves Agent 4 output
- Daily summary / briefing → retrieves Agent 6 output

**Out of scope (MVP):** Ad-hoc analysis beyond agent outputs; raw transaction queries; writing assumptions via chat; approving recommendations via chat.

```
Request params: ?message=<url-encoded message>&session_id=<uuid>

SSE event format:
event: message
data: {"type": "text", "content": "Based on today's cash position..."}

event: message
data: {"type": "text", "content": " EU Entity is €70K below minimum."}

event: done
data: {"run_id": "uuid", "source_agents": ["daily_cash", "liquidity_risk"]}
```

**Mock mode (build sessions):** Return a static pre-composed string streamed character-by-character. `ANTHROPIC_API_KEY` in `.env` as a placeholder. Real API wired in a dedicated post-Step-8 session.

---

## RATE LIMITING (App Backend)

```
GET  requests: 1000/min per user
POST requests: 100/min per user
File uploads:  10/min per user
SQS publish:   100 jobs/min per client (SQS native throttling)
```

---

## ROLE PERMISSIONS MATRIX

| Endpoint Category | Viewer | Analyst | TreasuryManager | CFO |
|---|---|---|---|---|
| Cash position (read) | ✅ | ✅ | ✅ | ✅ |
| File upload | ❌ | ✅ | ✅ | ✅ |
| Request recommendation | ❌ | ✅ | ✅ | ✅ |
| Approve / reject recommendation | ❌ | ❌ | ✅ | ✅ |
| Manage accounts | ❌ | ❌ | ✅ | ✅ |
| Manage FX rates | ❌ | ❌ | ✅ | ✅ |
| Manage investment policy / cutoffs | ❌ | ❌ | ❌ | ✅ |
| View audit log | ❌ | ❌ | ✅ | ✅ |
| Export audit log | ❌ | ❌ | ✅ | ✅ |
| Request forecast | ❌ | ✅ | ✅ | ✅ |
| Request CFO summary | ❌ | ✅ | ✅ | ✅ |

---

## BACKEND IMPLEMENTATION ORDER

| Session | Deliverable | Endpoints | Service | Status |
|---|---|---|---|---|
| **S0** | Shared Python Library | n/a (schemas, types, utils, SQS envelopes) | `core-cash-shared` | 🔨 Build first |
| **S1** | App Backend scaffold + Auth | `/health`, `/auth/*` | App Backend | ✅ Done (Step 1) |
| **S2** | AI Backend scaffold | `/health` (AI), SQS consumer loop, LangGraph skeleton | AI Backend | 🔨 Build now |
| **S3** | DB migrations + Cash Position | `/api/cash-position/*`, `/api/accounts`, `/api/metadata/*` | App Backend | 🔨 Build now (after S0) |
| **S4** | Liquidity Risk Agent (Agent 3) | `/api/liquidity-risk/*` | AI Backend + App Backend poll | 🔨 After S3 |
| **S5** | File Ingestion (CSV first) | `/api/files/*` | App Backend | 🔨 After S3 |
| **S6** | Recommendation flow (Agent 4 mocked) | `/api/recommendations/*` | App Backend + AI Backend | 🔨 After S4 |
| **S7** | Forecast scaffold (blocked) + Assumptions | `/api/forecast/assumptions`, `/api/forecast/request` → 503 | App Backend | 🔨 After S3 |
| **S8** | Config endpoints | `/api/config/fx-rates`, `/api/config/investment-*` | App Backend | 🔨 After S3 |
| **S9** | CFO Summary + Daily Briefing (Agents 6, 7 mocked) | `/api/cfo-summary/*`, `/api/daily-briefing/*` | AI Backend + App Backend | 🔨 After S6 |
| **S10** | Variance Agent (Agent 5, mocked) | `/api/forecast/variance/*` | AI Backend + App Backend | ⚠️ After Forecast unblocked |
| **S11** | Audit log + Approval service | `/api/audit-log/*` | App Backend | 🔨 After S6 |
| **S12** | Chat SSE | `/ai/chat/stream` | AI Backend | 🔨 After S9 |
| **S13** | BAI2, camt.053, MT940 parsers | `/api/files/upload` (format extensions) | App Backend | 🔨 After S5 |
| **S14** | Forecast unblock + Variance wire | Full forecast + variance | AI Backend | ⚠️ After opening balance resolved |
| **S15** | Real LLM wiring (Agents 4, 5, 6) | No new endpoints | AI Backend | ⚠️ Post-Step-8 sign-off |

---

## OPEN ITEMS (Must Resolve Before Indicated Session)

| # | Item | Blocks | Owner |
|---|---|---|---|
| 1 | Opening balance anchor rule (prior-day closing vs. other anchor) | S14 (Forecast unblock) | Paul + amit j |
| 2 | Investment cut-off time values per entity (USD, GBP) | S6 investment recs | amit j |
| 3 | Investment policy document per entity | S6 investment recs | amit j |
| 4 | PDF sample files for parser feasibility | S13 extensions | amit j |
| 5 | DOA policy config structure (approval hierarchy per entity) | S6 control field | Paul + amit j |

---

**Document Version:** 3.0
**Supersedes:** v2.0 (21 August 2026)
**Last Updated:** 22 August 2026
**Status:** Ready for Development