# API Endpoint Reference

All endpoints are served by **App Backend (port 8000)** unless noted. Frontend talks only to App Backend; never directly to AI Backend.

---

## Authentication

All endpoints except `/health` require:

```http
Authorization: Bearer <jwt_token>
```

**Token Source**: AWS Cognito (OAuth2 flow)

**JWT Claims**:
- `sub`: User UUID
- `email`: User email
- `cognito:groups`: Array of roles (["TreasuryManager"], ["CFO"], etc.)
- `exp`, `iat`: Token expiry / issuance time

**Validation**: App Backend validates RS256 signature using Cognito public key.

---

## Health Check

### GET /health
Check service readiness.

**Auth**: None

**Response 200**:
```json
{
  "status": "healthy",
  "timestamp": "2026-08-24T10:30:00Z",
  "services": {
    "postgres": "ok",
    "mongodb": "ok"
  }
}
```

---

## Cash Position

### POST /api/cash-position/request
Request a cash position calculation (async job).

**Auth**: Analyst, TreasuryManager, CFO

**Body**:
```json
{
  "cash_position_date": "2026-08-24"  // optional; defaults to today
}
```

**Response 202**:
```json
{
  "request_id": "uuid",
  "status": "queued",
  "queued_at": "2026-08-24T10:30:00Z",
  "estimated_completion": "5–10 seconds"
}
```

**Response 503**: Service unavailable (queue error)

**Notes**: Enqueues Agent 1 job to InProcessJobPublisher.

---

### GET /api/cash-position/{request_id}
Poll for cash position result.

**Auth**: Viewer, Analyst, TreasuryManager, CFO

**Response 202** (still processing):
```json
{
  "request_id": "uuid",
  "status": "processing",
  "queued_at": "2026-08-24T10:30:00Z"
}
```

**Response 200** (completed):
```json
{
  "request_id": "uuid",
  "status": "completed",
  "run_id": "mongo_doc_id",
  "entity_id": "uuid",
  "entity_name": "North America Region",
  "position_date": "2026-08-24",
  "total_balance_usd": 5000000.0,
  "usable_cash": 4500000.0,
  "od_headroom": 500000.0,
  "accounts": [
    {
      "account_id": "uuid",
      "account_name": "Operating - USD",
      "currency": "USD",
      "balance": 2000000.0,
      "od_limit": 500000.0,
      "od_utilised": 0.0,
      "include_in_position": true
    }
  ],
  "generated_at": "2026-08-24T10:30:00Z"
}
```

**Response 404**: Request not found

**Response 500**: Agent failed

**Notes**:
- Poll interval: 2 seconds
- Timeout: 60 seconds
- `usable_cash` = accounts WHERE include_in_cash_position=true
- `od_headroom` = computed, NOT stored (od_limit - od_utilised_amount)

---

## Liquidity Risk

### POST /api/liquidity-risk/request
Request liquidity risk assessment (async job).

**Auth**: Analyst, TreasuryManager, CFO

**Body**: (empty or optional date)

**Response 202**:
```json
{
  "request_id": "uuid",
  "status": "queued",
  "queued_at": "2026-08-24T10:30:00Z"
}
```

---

### GET /api/liquidity-risk/{request_id}
Poll for risk assessment result.

**Auth**: Viewer+

**Response 200**:
```json
{
  "request_id": "uuid",
  "status": "completed",
  "run_id": "mongo_doc_id",
  "entity_id": "uuid",
  "entity_name": "string",
  "assessment_date": "2026-08-24",
  "cash_position_balance_usd": 5000000.0,
  "cash_required_usd": 3000000.0,
  "coverage_ratio": 1.67,
  "warning_threshold_pct": 70,
  "is_warning": false,
  "shortfall_pts": 0,
  "shortfall_amount_usd": 0.0,
  "risk_level": "Low|Medium|High",
  "generated_at": "2026-08-24T10:30:00Z"
}
```

**Notes**:
- `coverage_ratio` = cash_position / cash_required
- `is_warning` = true if coverage_ratio < (warning_threshold_pct / 100)
- `warning_threshold_pct` = 70% per business rule (NEVER 80%)
- `shortfall_pts` = Agent 3's internal scoring (0–100)

---

## File Upload

### POST /api/files/upload
Upload bank statement, AR, or AP CSV/BAI2/MT940/camt.053 file.

**Auth**: Analyst, TreasuryManager, CFO

**Body**: multipart/form-data
```
file: <binary>
file_type: "bank_statement" | "ar_data" | "ap_data"
entity_id: "uuid"  (optional; inferred from file if omitted)
```

**Response 202**:
```json
{
  "file_id": "uuid",
  "status": "processing",
  "uploaded_at": "2026-08-24T10:30:00Z",
  "filename": "statement_2026_08.csv"
}
```

**Response 422**:
```json
{
  "error": {
    "code": "VALIDATION_FILE_TOO_LARGE",
    "message": "File must be < 10 MB"
  }
}
```

**Response 503**: Parser failed (error_code = VALIDATION_UNSUPPORTED_FORMAT, VALIDATION_MISSING_COLUMN, VALIDATION_EMPTY_FILE)

**Notes**:
- File formats: CSV, BAI2, MT940, camt.053
- Max file size: 10 MB
- Auto-detects format via FileFormatDetector
- Creates source_file record; triggers async parsing job
- Poll GET /api/files/{file_id} for status

---

### GET /api/files/{file_id}
Poll for file parsing result.

**Auth**: Viewer+

**Response 200**:
```json
{
  "file_id": "uuid",
  "status": "success",
  "file_type": "bank_statement",
  "filename": "statement_2026_08.csv",
  "rows_imported": 42,
  "uploaded_by": "alice@company.com",
  "uploaded_at": "2026-08-24T10:30:00Z"
}
```

**Response 422**: Parsing error
```json
{
  "file_id": "uuid",
  "status": "failed",
  "error_message": "Missing required column: 'closing_balance'"
}
```

---

## Forecast

### POST /api/forecast/request
Request forecast calculation (async job; Agent 2).

**Auth**: Analyst, TreasuryManager, CFO

**Body**:
```json
{
  "horizon_days": 7,  // optional; default 7
  "cash_position_date": "2026-08-24",  // optional
  "policy_id": "policy_default"  // optional
}
```

**Response 202**:
```json
{
  "forecast_id": "uuid",
  "status": "queued",
  "queued_at": "2026-08-24T10:30:00Z",
  "horizon_days": 7
}
```

---

### GET /api/forecast/{forecast_id}
Poll for forecast result.

**Auth**: Viewer+

**Response 202** (still processing):
```json
{
  "forecast_id": "uuid",
  "status": "queued",
  "queued_at": "2026-08-24T10:30:00Z"
}
```

**Response 200** (completed; data_status="partial"):
```json
{
  "forecast_id": "uuid",
  "status": "completed",
  "run_id": "mongo_doc_id",
  "entity_id": "uuid",
  "entity_name": "string",
  "generated_at": "2026-08-24T10:30:00Z",
  "horizon_days": 30,
  "data_status": "partial",
  "opening_balance_usd": 1000000.0,
  "forecast_rows": [
    {
      "forecast_date": "2026-08-25",
      "opening_balance_usd": 1000000.0,
      "projected_inflows_usd": 50000.0,
      "projected_outflows_usd": 30000.0,
      "projected_closing_usd": 1020000.0,
      "confidence_band_low_usd": 867000.0,
      "confidence_band_high_usd": 1173000.0,
      "assumptions_applied": ["assumption_id_1"]
    }
  ],
  "assumptions_used": 3,
  "assumptions_skipped": 1,
  "forecast_accuracy_pct": null,
  "notes": ["Confidence bands: ±15% placeholder"]
}
```

**Response 200** (blocked; no bank statement):
```json
{
  "forecast_id": "uuid",
  "status": "failed",
  "error": "OPENING_BALANCE_UNRESOLVED: No bank statement balance found for include_in_cash_position accounts",
  "data_status": "blocked",
  "blocked_reason": "OPENING_BALANCE_UNRESOLVED",
  "forecast_rows": [],
  "opening_balance_usd": null,
  "assumptions_used": 3,
  "assumptions_skipped": 1,
  "message": "Upload bank statement data to unblock forecast."
}
```

**Response 404**: Forecast not found

**Notes**:
- `data_status="blocked"`: Opening balance unresolved; forecast_rows empty
- `data_status="partial"`: Forecast calculated but may use placeholder assumptions
- `forecast_accuracy_pct`: NULL until Agent 5 runs (post-variance)
- Confidence bands ±15% are placeholder (post-MVP: ML model)

---

### GET /api/forecast/latest
Get the most recent forecast (regardless of data_status).

**Auth**: Viewer+

**Response 200**: Same as GET /api/forecast/{forecast_id}

**Response 404**: No forecast ever run

---

### GET /api/forecast/assumptions
List all active manual assumptions.

**Auth**: Viewer+

**Response 200**:
```json
{
  "assumptions": [
    {
      "id": "uuid",
      "entity_id": "uuid",
      "entity_name": "string",
      "currency": "USD",
      "direction": "Inflow",
      "amount": 50000.0,
      "date": "2026-08-25",
      "category": "Payroll",
      "description": "Q3 bonus payout",
      "confidence_pct": 85,
      "included_in_forecast": true,  // derived: confidence_pct >= threshold
      "created_by": "alice@company.com",
      "created_at": "2026-08-24T10:00:00Z",
      "updated_at": "2026-08-24T10:00:00Z"
    }
  ]
}
```

**Notes**:
- Filters by `deleted_at IS NULL`
- `included_in_forecast` derived from `confidence_pct >= system_config.forecast_confidence_threshold`
- Default threshold: 50%

---

### POST /api/forecast/assumptions
Create a new manual assumption.

**Auth**: Analyst, TreasuryManager, CFO

**Body**:
```json
{
  "entity_id": "uuid",
  "currency": "USD",
  "direction": "Inflow|Outflow",
  "amount": 50000.0,
  "date": "2026-08-25",
  "category": "Payroll|Tax|Investment|Loan Repayment|Capex|Operating|Other",
  "description": "Q3 bonus payout",
  "confidence_pct": 85
}
```

**Response 201**:
```json
{
  "id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "currency": "USD",
  "direction": "Inflow",
  "amount": 50000.0,
  "date": "2026-08-25",
  "category": "Payroll",
  "description": "Q3 bonus payout",
  "confidence_pct": 85,
  "included_in_forecast": true,
  "created_by": "alice@company.com",
  "created_at": "2026-08-24T10:00:00Z",
  "updated_at": "2026-08-24T10:00:00Z"
}
```

**Response 422**: Validation error
- direction not "Inflow" or "Outflow"
- amount <= 0
- date < today
- category not recognized
- confidence_pct outside 0–100
- entity_id doesn't exist for this client

**Side Effect**: Triggers forecast re-run job (non-blocking; logged warning if fails)

**Audit**: Writes assumption.created event

---

### PUT /api/forecast/assumptions/{assumption_id}
Update an assumption.

**Auth**: Analyst, TreasuryManager, CFO

**Body**: Same as POST

**Response 200**: Updated assumption (same schema as POST response)

**Response 404**: Assumption not found

**Response 422**: Validation error (same as POST)

**Side Effect**: Triggers forecast re-run job

**Audit**: Writes assumption.updated event

---

### DELETE /api/forecast/assumptions/{assumption_id}
Soft-delete an assumption.

**Auth**: Analyst, TreasuryManager, CFO

**Response 200**:
```json
{
  "status": "deleted"
}
```

**Response 404**: Assumption not found

**Side Effect**: Triggers forecast re-run job

**Audit**: Writes assumption.deleted event

---

## Recommendations & Approval

### POST /api/recommendations/request
Request recommendation generation (async job; Agent 4).

**Auth**: Analyst, TreasuryManager, CFO

**Body**:
```json
{
  "cash_position_date": "2026-08-24",  // optional
  "policy_id": "policy_default"  // optional
}
```

**Response 202**:
```json
{
  "request_id": "uuid",
  "status": "queued",
  "queued_at": "2026-08-24T10:30:00Z",
  "estimated_completion": "30–60 seconds"
}
```

---

### GET /api/recommendations/{request_id}
Poll for recommendations.

**Auth**: Viewer+

**Response 200** (completed):
```json
{
  "request_id": "uuid",
  "status": "completed",
  "run_id": "mongo_doc_id",
  "generated_at": "2026-08-24T10:30:00Z",
  "recommendation_count": 3,
  "recommendations": [
    {
      "id": "rec_123",
      "what": "Invest USD 500k in money market fund",
      "why": "Excess liquidity; 7-day forecast shows +USD 600k",
      "when": "2026-08-25",
      "control": "Transfer to investment account",
      "expected_return": "0.5% yield",
      "priority": 1,
      "approval_status": "Pending|Approved|Rejected|Overridden|Blocked",
      "approved_by": "uuid",
      "approved_at": "2026-08-24T11:00:00Z",
      "notes": "Approved by CFO",
      "rejection_reason": null,
      "action_taken": null,
      "override_reason": null
    }
  ],
  "reasoning_trace": [
    {
      "step": 1,
      "agent": "daily_cash",
      "status": "complete",
      "duration_ms": 220
    }
  ]
}
```

**Important**: `blocked_count` and `blocked_reasons` are **internal fields** — never returned in API

**Response 404**: Request not found

**Notes**:
- `approval_status="Blocked"`: Policy violation detected by Agent 7; hidden from frontend
- `reasoning_trace`: Mock timing (Session 15 wires real durations)

---

### GET /api/recommendations
List all recommendations (paginated).

**Auth**: Viewer+

**Query Params**:
- `page`: 1 (default)
- `page_size`: 20 (default)
- `status`: filter by "queued", "processing", "completed", "failed" (optional)

**Response 200**:
```json
{
  "recommendations": [
    {
      "request_id": "uuid",
      "status": "completed",
      "generated_at": "2026-08-24T10:30:00Z",
      "recommendation_count": 3,
      "pending_approvals": 2
    }
  ],
  "total": 15,
  "page": 1,
  "page_size": 20
}
```

---

### POST /api/recommendations/{recommendation_id}/approve
Approve a recommendation.

**Auth**: TreasuryManager, CFO

**Body**:
```json
{
  "notes": "Approved by CFO. Monitor forex exposure."
}
```

**Response 200**:
```json
{
  "id": "rec_123",
  "approval_status": "Approved",
  "approved_by": "uuid",
  "approved_at": "2026-08-24T11:00:00Z",
  "notes": "Approved by CFO. Monitor forex exposure."
}
```

**Response 409**: Already actioned
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Recommendation has already been actioned."
  }
}
```

**Response 404**: Recommendation not found

**Audit**: Writes recommendation.approved event

**Notes**: Record only — no autonomous execution.

---

### POST /api/recommendations/{recommendation_id}/reject
Reject a recommendation.

**Auth**: TreasuryManager, CFO

**Body**:
```json
{
  "reason": "Market conditions not favorable; deferring to next quarter."
}
```

**Response 200**:
```json
{
  "id": "rec_123",
  "approval_status": "Rejected",
  "rejected_by": "uuid",
  "rejected_at": "2026-08-24T11:00:00Z",
  "reason": "Market conditions not favorable; deferring to next quarter."
}
```

**Response 409**: Already actioned

**Response 404**: Recommendation not found

**Audit**: Writes recommendation.rejected event

---

### POST /api/recommendations/{recommendation_id}/override
Override recommendation with manual action.

**Auth**: TreasuryManager, CFO

**Body**:
```json
{
  "action_taken": "Invested USD 300k (less than recommendation) due to liquidity constraints",
  "notes": "Will reassess next week"
}
```

**Response 200**:
```json
{
  "id": "rec_123",
  "approval_status": "Overridden",
  "overridden_by": "uuid",
  "overridden_at": "2026-08-24T11:00:00Z",
  "action_taken": "Invested USD 300k (less than recommendation)",
  "notes": "Will reassess next week"
}
```

**Response 409**: Already actioned

**Response 404**: Recommendation not found

**Audit**: Writes recommendation.overridden event

---

## Variance Explanation

### POST /api/forecast/variance/request
Request variance analysis (async job; Agent 5).

**Auth**: Analyst, TreasuryManager, CFO

**Body**: (empty)

**Response 202**:
```json
{
  "variance_id": "uuid",
  "status": "queued",
  "queued_at": "2026-08-24T10:30:00Z"
}
```

**Response 503**: Variance requires completed forecast (blocked or unavailable data)

**Notes**: Enqueues Agent 5 job. Reads latest forecast_runs and bank_statement actuals.

---

### GET /api/forecast/variance/{variance_id}
Poll for variance result.

**Auth**: Viewer+

**Response 200** (completed):
```json
{
  "variance_id": "uuid",
  "status": "completed",
  "run_id": "mongo_doc_id",
  "generated_at": "2026-08-24T10:30:00Z",
  "variance_summary": "Forecast overestimated inflows by USD 50k; AR delayed 2 days",
  "variance_detail": [
    {
      "component": "AR Collection",
      "forecasted": 100000.0,
      "actual": 50000.0,
      "variance_amount": -50000.0,
      "variance_pct": -50,
      "explanation": "3 customers delayed payment by 2 days"
    }
  ]
}
```

**Response 404**: Variance not found

---

## CFO Summary & Briefing

### POST /api/cfo/report/request
Request CFO summary (async job; Agent 6).

**Auth**: Analyst, TreasuryManager, CFO

**Body**: (empty or optional date)

**Response 202**:
```json
{
  "request_id": "uuid",
  "status": "queued",
  "queued_at": "2026-08-24T10:30:00Z"
}
```

---

### GET /api/cfo/report/{request_id}
Poll for CFO summary.

**Auth**: Viewer+

**Response 200**:
```json
{
  "request_id": "uuid",
  "status": "completed",
  "run_id": "mongo_doc_id",
  "report_date": "2026-08-24",
  "executive_summary": "Cash position strong. 3 investment opportunities identified.",
  "top_risks": [
    {
      "rank": 1,
      "risk": "Seasonal Q4 outflow spike",
      "mitigation": "Pre-arrange credit line renewal"
    }
  ],
  "top_recommendations": [
    {
      "id": "rec_1",
      "what": "Invest USD 500k",
      "why": "Excess liquidity",
      "priority": 1
    }
  ],
  "forecast_outlook": [
    {
      "date": "2026-08-25",
      "projected_closing_usd": 5100000.0,
      "confidence_band_low_usd": 4335000.0,
      "confidence_band_high_usd": 5865000.0
    }
  ],
  "generated_at": "2026-08-24T10:30:00Z"
}
```

---

### POST /api/cfo/briefing/email
Email CFO briefing (async delivery).

**Auth**: TreasuryManager, CFO

**Body**:
```json
{
  "to": ["cfo@company.com"],
  "briefing_type": "morning|evening"
}
```

**Response 202**:
```json
{
  "status": "queued",
  "sent_at": "2026-08-24T10:30:00Z"
}
```

**Response 501**: Not yet implemented

---

## Chat (SSE Streaming)

### POST /api/chat/stream
Stream chat response (real-time; no job queue).

**Auth**: Viewer+

**Body**:
```json
{
  "messages": [
    {
      "role": "user",
      "content": "What is our 30-day cash forecast?"
    }
  ]
}
```

**Response 200** (SSE stream):
```
event: context
data: {"total_balance_usd": 5000000.0, "risk_level": "Low", ...}

event: token
data: "Based on your current cash position of USD 5 million,"

event: token
data: " the 30-day forecast shows strong liquidity."

event: done
data: null
```

**Events**:

| Event | Meaning | Data |
|-------|---------|------|
| `context` | Treasury data snapshot (first event) | JSON object with balances, risks, forecast |
| `token` | LLM output chunk | Text string (one chunk) |
| `done` | Stream complete | null |
| `error` | Error occurred | JSON with error_code and message |

**Notes**:
- No job queue; synchronous stream
- Frontend parses SSE events (split on `\n\n`, extract `event:` and `data:` lines)
- Read-only; no transaction execution suggested

---

## Configuration

### GET /api/config/system
Get all system configuration values.

**Auth**: Viewer+

**Response 200**:
```json
{
  "forecast_confidence_threshold": 50,
  "warning_threshold_pct": 70,
  "significant_outflow_pct": 10
}
```

---

### PUT /api/config/system/{config_key}
Update system configuration (only writable keys).

**Auth**: TreasuryManager, CFO

**Body**:
```json
{
  "config_val": "60"
}
```

**Writable Keys** (only these 3):
- `forecast_confidence_threshold`
- `warning_threshold_pct`
- `significant_outflow_pct`

**Response 200**: Updated value

**Response 400**: Key not writable

**Audit**: Writes config.updated event

---

### GET /api/config/fx-rates
Get current FX rates.

**Auth**: Viewer+

**Query Params**:
- `rate_date`: "2026-08-24" (optional; default today)

**Response 200**:
```json
{
  "rates": [
    {
      "currency_from": "EUR",
      "currency_to": "USD",
      "rate": 1.08,
      "rate_date": "2026-08-24"
    }
  ]
}
```

---

### POST /api/config/fx-rates
Create FX rate (one per currency_from per date).

**Auth**: Analyst, TreasuryManager, CFO

**Body**:
```json
{
  "currency_from": "EUR",
  "currency_to": "USD",
  "rate": 1.08,
  "rate_date": "2026-08-24"
}
```

**Response 201**: Created rate

**Response 422**: Duplicate (currency_from, rate_date)

**Audit**: Writes fx_rate.created event

---

### GET /api/config/investment-policy
Get active investment policy.

**Auth**: Viewer+

**Response 200**:
```json
{
  "id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "min_cash_balance": 1000000.0,
  "min_days_cash": 14,
  "max_single_investment": 500000.0,
  "max_total_investment": 2000000.0,
  "counterparty_limit": 300000.0,
  "effective_date": "2026-01-01",
  "notes": "Conservative policy; prioritize safety over yield",
  "is_active": true,
  "created_at": "2026-01-01T00:00:00Z"
}
```

---

### POST /api/config/investment-policy
Create investment policy (replaces old policy).

**Auth**: TreasuryManager, CFO

**Body**: Same as GET response (minus created_at, is_active, id)

**Response 201**: Created policy

**Audit**: Writes investment_policy.created event

**Notes**: Soft-deletes old policy (sets is_active=false)

---

### GET /api/config/investment-cutoff
Get investment cutoff rules.

**Auth**: Viewer+

**Response 200**:
```json
{
  "id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "cutoff_date": "2026-10-01",
  "approval_threshold": 100000.0,
  "notes": "Q4 moratorium on new investments",
  "created_at": "2026-09-01T00:00:00Z"
}
```

---

### POST /api/config/investment-cutoff
Create/update investment cutoff.

**Auth**: TreasuryManager, CFO

**Body**: Same as GET (minus created_at, id)

**Response 201**: Created cutoff

**Audit**: Writes investment_cutoff.created event

---

## Audit Log

### GET /api/audit/log
Retrieve audit log entries.

**Auth**: Viewer+ (but can only see own client's audit trail)

**Query Params**:
- `page`: 1 (default)
- `page_size`: 50 (default)
- `action`: filter by action (optional, e.g., "assumption.created")
- `start_date`: ISO date (optional)
- `end_date`: ISO date (optional)

**Response 200**:
```json
{
  "entries": [
    {
      "id": "uuid",
      "action": "assumption.created",
      "entity_type": "manual_assumption",
      "entity_id": "uuid",
      "user_id": "uuid",
      "before_state": null,
      "after_state": {
        "direction": "Inflow",
        "amount": 50000.0,
        "confidence_pct": 85
      },
      "ip_address": "192.0.2.1",
      "created_at": "2026-08-24T10:30:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 50
}
```

**Notes**:
- Append-only (immutable)
- Timestamps always UTC
- `before_state` null for create operations

---

## Error Codes

All error responses include:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "severity": "error|warning"
  }
}
```

| Code | HTTP | When | Handling |
|------|------|------|----------|
| AUTH_TOKEN_MISSING | 401 | No Authorization header | Redirect to login |
| AUTH_TOKEN_INVALID | 401 | JWT signature invalid | Refresh token or re-login |
| AUTH_TOKEN_EXPIRED | 401 | Token expiry passed | Refresh token |
| AUTH_PERMISSION_DENIED | 403 | User role insufficient | Show "Access Denied" message |
| VALIDATION_REQUIRED_FIELD | 422 | Missing required field | Highlight form field |
| VALIDATION_INVALID_FORMAT | 422 | Field format wrong | Show validation error |
| VALIDATION_FILE_TOO_LARGE | 422 | File > 10 MB | Show file size error |
| VALIDATION_UNSUPPORTED_FORMAT | 422 | File format not recognized | Show file format error |
| VALIDATION_MISSING_COLUMN | 422 | Required column missing | Show column name in error |
| OPENING_BALANCE_UNRESOLVED | 503 | No bank statement balance | Show "Upload bank data to unblock" |
| FX_RATE_MISSING | 422 | FX rate not found for currency | Show "Add FX rate" prompt |
| INVESTMENT_POLICY_NOT_UPLOADED | 422 | No policy configured | Show "Configure policy first" |
| JOB_NOT_FOUND | 404 | Request ID not found | Retry or show error |
| JOB_STILL_PROCESSING | 202 | Job still queued/processing | Continue polling |
| JOB_FAILED | 500 | Agent error | Show "Retry" button + error details |
| DATA_STALE | 422 | Data older than expected | Trigger re-run |
| AGENT_ERROR | 503 | Queue publish failed | Show retry prompt |
| INTERNAL_ERROR | 500 | Unhandled exception | Contact support |

---

## Async Polling Pattern (Frontend Best Practice)

```javascript
async function pollForecast(requestId) {
  const maxRetries = 60;  // 60 × 2s = 120s timeout
  let retries = 0;

  while (retries < maxRetries) {
    const response = await fetch(
      `/api/forecast/${requestId}`,
      {
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        }
      }
    );

    if (response.status === 200) {
      const result = await response.json();
      if (result.status === "completed") {
        return result;  // Success
      }
      if (result.status === "failed") {
        throw new Error(result.error);
      }
    }

    if (response.status === 404) {
      throw new Error("Forecast not found");
    }

    if (response.status === 500) {
      throw new Error("Server error");
    }

    // Still processing (202)
    await sleep(2000);  // Wait 2 seconds
    retries++;
  }

  throw new Error("Forecast request timeout after 120 seconds");
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
```

Next: [Repository Structure →](04-repo-structure.md)
