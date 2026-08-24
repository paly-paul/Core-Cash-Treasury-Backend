# Database Schema Reference

## Section A — PostgreSQL Tables

Core Cash uses PostgreSQL for transactional state. **App Backend** owns read/write access; **AI Backend** reads only.

---

### Table: `client`
**Purpose**: Multi-tenant client container.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `name` | VARCHAR(255) | ❌ | — | Client display name (e.g., "Acme Corp") |
| `slug` | VARCHAR(100) | ❌ | — | URL-safe identifier; unique |
| `created_at` | TIMESTAMP | ❌ | now() | Record creation time |

**Indexes**: UNIQUE (slug)

---

### Table: `legal_entity`
**Purpose**: Business entities within a client (divisions, subsidiaries).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `name` | VARCHAR(255) | ❌ | — | Entity name (e.g., "North America Region") |
| `base_currency` | VARCHAR(3) | ❌ | "USD" | ISO 4217 code (USD, EUR, GBP, etc.) |
| `country_code` | VARCHAR(2) | ✅ | — | ISO 3166-1 alpha-2 code |
| `created_at` | TIMESTAMP | ❌ | now() | Record creation time |

**Foreign Keys**: client_id → client.id

---

### Table: `bank`
**Purpose**: Financial institutions.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `name` | VARCHAR(255) | ❌ | — | Bank name (e.g., "JP Morgan") |
| `swift_code` | VARCHAR(11) | ✅ | — | SWIFT code for wire transfer identification |
| `created_at` | TIMESTAMP | ❌ | now() | Record creation time |

**Foreign Keys**: client_id → client.id

---

### Table: `account` (aka "bank_accounts")
**Purpose**: Business bank accounts.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `entity_id` | UUID | ❌ | — | Foreign key → legal_entity.id |
| `bank_id` | UUID | ✅ | — | Foreign key → bank.id |
| `account_name` | VARCHAR(255) | ❌ | — | Display name (e.g., "Operating Account - USD") |
| `bank_account_number` | VARCHAR(50) | ✅ | — | IBAN, BBAN, or bank-specific account identifier |
| `currency` | VARCHAR(3) | ❌ | — | ISO 4217 code |
| `min_threshold` | NUMERIC(15,2) | ❌ | 0 | Minimum balance threshold (alert-only, not enforced) |
| `restricted_flag` | BOOLEAN | ❌ | false | If true, account excluded from certain operations |
| `od_limit` | NUMERIC(15,2) | ✅ | — | Overdraft limit (when exists); nullable if none |
| `od_utilised_amount` | NUMERIC(15,2) | ✅ | — | Current overdraft drawn; nullable if none |
| `refresh_frequency` | VARCHAR(20) | ❌ | "Daily" | Polling frequency for bank data (Daily, Weekly, Manual) |
| `include_in_cash_position` | BOOLEAN | ❌ | true | **CRITICAL**: if FALSE, balance excluded from usable_cash |
| `is_active` | BOOLEAN | ❌ | true | Soft-delete flag (when false, not queried by agents) |
| `created_at` | TIMESTAMP | ❌ | now() | Record creation time |

**Foreign Keys**: client_id → client.id, entity_id → legal_entity.id, bank_id → bank.id

**Business Rules**:
- `od_headroom`: **NOT stored**. Computed as `od_limit - od_utilised_amount` (calculated at query time)
- `include_in_cash_position = FALSE`: Account balance never included in Agent 1 cash position sum
- All account balances must be positive after importing bank statements; negative balances indicate overdraft draw

---

### Table: `statement` (aka "bank_statement")
**Purpose**: Daily closing balances per account (snapshots from bank feeds).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `account_id` | UUID | ❌ | — | Foreign key → account.id |
| `statement_date` | DATE | ❌ | — | Close-of-business date (YYYY-MM-DD) |
| `closing_balance` | NUMERIC(15,2) | ❌ | — | EOD balance in account currency |
| `available_balance` | NUMERIC(15,2) | ✅ | — | Available balance (may differ from closing) |
| `currency` | VARCHAR(3) | ❌ | — | ISO 4217 code |
| `source` | VARCHAR(50) | ✅ | — | Data source (e.g., "BAI2", "MT940", "camt.053") |
| `ingested_at` | TIMESTAMP | ❌ | now() | Import time from file parser |

**Indexes**: UNIQUE (account_id, statement_date)

**Foreign Keys**: account_id → account.id

**Business Rules**:
- Agent 2 (Forecast) reads latest `closing_balance WHERE account.include_in_cash_position = TRUE` to set `opening_balance_usd`
- If no statement exists for an account with `include_in_cash_position = TRUE`, forecast is **blocked** with OPENING_BALANCE_UNRESOLVED

---

### Table: `transaction`
**Purpose**: Individual transactions parsed from bank statements (detail ledger).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `account_id` | UUID | ❌ | — | Foreign key → account.id |
| `statement_id` | UUID | ✅ | — | Foreign key → statement.id (optional; may be inferred) |
| `transaction_date` | DATE | ❌ | — | Transaction effective date |
| `value_date` | DATE | ✅ | — | Settlement date (may differ from transaction_date) |
| `amount` | NUMERIC(15,2) | ❌ | — | Transaction value (always positive; see direction) |
| `direction` | VARCHAR(10) | ❌ | — | "Inflow" or "Outflow" |
| `description` | TEXT | ✅ | — | Memo / reference text |
| `reference` | VARCHAR(255) | ✅ | — | Bank reference ID (for deduplication) |
| `created_at` | TIMESTAMP | ❌ | now() | Import time |

**Foreign Keys**: account_id → account.id, statement_id → statement.id

---

### Table: `ar_schedule` (aka "ar_data")
**Purpose**: Accounts Receivable aging schedule.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `entity_id` | UUID | ❌ | — | Foreign key → legal_entity.id |
| `counterparty_name` | VARCHAR(255) | ❌ | — | Customer name |
| `expected_date` | DATE | ❌ | — | Expected collection date |
| `amount` | NUMERIC(15,2) | ❌ | — | Invoice or receivable amount |
| `currency` | VARCHAR(3) | ❌ | — | ISO 4217 code |
| `category` | VARCHAR(50) | ✅ | "AR" | Always "AR" for this table |
| `source_file_id` | UUID | ✅ | — | Foreign key → source_file.id (which file imported this row) |
| `created_at` | TIMESTAMP | ❌ | now() | Import time |

**Foreign Keys**: client_id → client.id, entity_id → legal_entity.id, source_file_id → source_file.id

**Usage by Agents**:
- Agent 5 (Variance): Reads to compare forecasted vs. actual AR collection
- Agent 2 (Forecast): Post-MVP will project inflows based on AR aging (currently uses manual assumptions only)

---

### Table: `ap_schedule` (aka "ap_data")
**Purpose**: Accounts Payable aging schedule.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `entity_id` | UUID | ❌ | — | Foreign key → legal_entity.id |
| `vendor_name` | VARCHAR(255) | ❌ | — | Vendor / supplier name |
| `due_date` | DATE | ❌ | — | Payment due date |
| `amount` | NUMERIC(15,2) | ❌ | — | Invoice amount due |
| `currency` | VARCHAR(3) | ❌ | — | ISO 4217 code |
| `category` | VARCHAR(50) | ✅ | "AP" | Always "AP" for this table |
| `source_file_id` | UUID | ✅ | — | Foreign key → source_file.id |
| `created_at` | TIMESTAMP | ❌ | now() | Import time |

**Foreign Keys**: client_id → client.id, entity_id → legal_entity.id, source_file_id → source_file.id

**Usage by Agents**:
- Agent 5 (Variance): Reads to compare forecasted vs. actual AP payment timing
- Agent 2 (Forecast): Post-MVP will project outflows based on AP aging (currently uses manual assumptions only)

---

### Table: `manual_assumptions`
**Purpose**: User-entered forecast assumptions (inflows/outflows beyond AR/AP).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `entity_id` | UUID | ❌ | — | Foreign key → legal_entity.id |
| `description` | TEXT | ❌ | — | What this assumption is for (e.g., "Q3 bonus payout") |
| `amount` | NUMERIC(15,2) | ❌ | — | Transaction value (always positive) |
| `currency` | VARCHAR(3) | ❌ | — | ISO 4217 code |
| `date` | DATE | ✅ | — | Transaction date (added Session 13) |
| `expected_date` | DATE | ✅ | — | Expected settlement date (legacy; use `date` if available) |
| `direction` | VARCHAR(10) | ❌ | — | "Inflow" or "Outflow" |
| `confidence_pct` | NUMERIC(5,2) | ❌ | — | Likelihood 0–100% (threshold: 50% default from system_config) |
| `category` | VARCHAR(100) | ✅ | — | User-assigned category (e.g., "Payroll", "Tax", "Capex") |
| `created_by` | UUID | ✅ | — | Foreign key → users.id (who created this) |
| `created_at` | TIMESTAMP | ❌ | now() | Creation time |
| `updated_at` | TIMESTAMP | ✅ | — | Last update (added Session 13) |
| `deleted_at` | TIMESTAMP | ✅ | — | Soft-delete timestamp (NULL = active) |

**Foreign Keys**: client_id → client.id, entity_id → legal_entity.id, created_by → users.id

**Business Rules**:
- **Soft-delete only**: Set `deleted_at` (never hard DELETE)
- **Included in Forecast**: Only if `confidence_pct >= system_config.forecast_confidence_threshold` (default 50)
- **Trigger re-run**: POST/PUT/DELETE on assumptions triggers forecast job (non-blocking)

---

### Table: `source_file`
**Purpose**: Audit trail for file uploads (CSV, BAI2, MT940, camt.053).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `uploaded_by` | UUID | ✅ | — | Foreign key → users.id (who uploaded) |
| `file_type` | VARCHAR(50) | ❌ | — | "bank_statement", "ar_data", "ap_data" |
| `file_format` | VARCHAR(20) | ✅ | — | "CSV", "BAI2", "MT940", "camt.053" |
| `filename` | VARCHAR(500) | ✅ | — | Original filename |
| `rows_imported` | INTEGER | ✅ | — | Number of rows/records parsed |
| `status` | VARCHAR(20) | ❌ | "pending" | "pending", "success", "failed" |
| `error_message` | TEXT | ✅ | — | Parse error details if status=failed |
| `uploaded_at` | TIMESTAMP | ❌ | now() | Upload time |

**Foreign Keys**: client_id → client.id, uploaded_by → users.id

---

### Table: `job_status`
**Purpose**: Async job tracking (request ID → result).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `job_id` | UUID | ❌ | — | **Request ID returned to frontend** (unique per client) |
| `job_type` | VARCHAR(50) | ❌ | — | "forecast", "action_recommendation", etc. |
| `status` | VARCHAR(20) | ❌ | "queued" | "queued", "processing", "completed", "failed" |
| `requested_by` | UUID | ✅ | — | Foreign key → users.id (who requested) |
| `requested_at` | TIMESTAMP | ❌ | now() | Request time |
| `completed_at` | TIMESTAMP | ✅ | — | Completion time (set when status=completed/failed) |
| `result_id` | TEXT | ✅ | — | MongoDB document ID (e.g., ObjectId as string) |
| `error_message` | TEXT | ✅ | — | Agent error details if status=failed |

**Indexes**: UNIQUE (job_id), (job_id), (client_id, status)

**Foreign Keys**: client_id → client.id, requested_by → users.id

**Workflow**:
1. POST /api/forecast/request → create job_status (status=queued)
2. App Backend publishes JobEnvelope
3. AI Backend consumer processes, writes MongoDB result
4. AI Backend updates job_status (status=completed, result_id=mongo_doc._id)
5. Frontend polls GET /api/forecast/{job_id} → App Backend reads job_status, then fetches MongoDB

---

### Table: `audit_log`
**Purpose**: Immutable audit trail (no UPDATE or DELETE).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `user_id` | UUID | ✅ | — | Foreign key → users.id (who made the change) |
| `action` | VARCHAR(100) | ❌ | — | "assumption.created", "recommendation.approved", etc. |
| `entity_type` | VARCHAR(50) | ✅ | — | "manual_assumption", "recommendation", "fx_rates" |
| `entity_id` | UUID | ✅ | — | ID of entity modified |
| `before_state` | JSONB | ✅ | — | Field values before change |
| `after_state` | JSONB | ✅ | — | Field values after change |
| `ip_address` | INET | ✅ | — | Client IP (captured by middleware) |
| `created_at` | TIMESTAMP | ❌ | now() | Event time |

**Indexes**: (client_id), (created_at)

**Foreign Keys**: client_id → client.id, user_id → users.id

**Business Rule**: **APPEND-ONLY**. No UPDATE or DELETE permitted. Compliance requires complete history.

---

### Table: `fx_rates`
**Purpose**: Foreign exchange rates (for multi-currency consolidation).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `currency_from` | VARCHAR(3) | ❌ | — | Source currency (ISO 4217) |
| `currency_to` | VARCHAR(3) | ❌ | "USD" | Target currency (ISO 4217; default USD) |
| `rate` | NUMERIC(18,6) | ❌ | — | Exchange rate (1 unit of from = rate units of to) |
| `rate_date` | DATE | ❌ | — | Effective date of this rate |
| `entered_by` | UUID | ❌ | — | Foreign key → users.id (who entered) |
| `entered_at` | TIMESTAMP | ❌ | now() | Entry time |

**Indexes**: UNIQUE (client_id, currency_from, rate_date)

**Foreign Keys**: client_id → client.id, entered_by → users.id

**Usage by Agents**:
- Agent 1 (Cash Position): Converts all account balances to USD for consolidated position
- Raises FX_RATE_MISSING error if rate not found

---

### Table: `system_config`
**Purpose**: Runtime configuration (runtime overrides).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `config_key` | VARCHAR(100) | ❌ | — | Config setting name |
| `config_val` | TEXT | ❌ | — | Value (stored as string; parsed at read time) |
| `updated_by` | UUID | ✅ | — | Foreign key → users.id (last editor) |
| `updated_at` | TIMESTAMP | ❌ | now() | Last update time |

**Indexes**: UNIQUE (client_id, config_key)

**Foreign Keys**: client_id → client.id, updated_by → users.id

**Writable Keys** (only these 3; others are read-only in App Backend):
1. `forecast_confidence_threshold`: Default 50 (Agent 2 filters assumptions where confidence_pct >= this)
2. `warning_threshold_pct`: Default 70 (Agent 3 flags liquidity if cash < 70% of need; **NEVER 80** per business rule)
3. `significant_outflow_pct`: Default 10 (Agent 3 threshold for significant outflow detection)

---

### Table: `investment_policy`
**Purpose**: Investment limits and counterparty exposure rules.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `entity_id` | UUID | ❌ | — | Foreign key → legal_entity.id |
| `entity_name` | VARCHAR(255) | ✅ | — | Cached entity name (denormalization for UI) |
| `min_cash_balance` | NUMERIC(15,2) | ❌ | — | Minimum cash required at all times |
| `min_days_cash` | INTEGER | ✅ | — | Minimum days of operating cash (alternative to fixed amount) |
| `max_single_investment` | NUMERIC(15,2) | ❌ | — | Max investable amount per counterparty |
| `max_total_investment` | NUMERIC(15,2) | ❌ | — | Max total investment capacity |
| `counterparty_limit` | NUMERIC(15,2) | ✅ | — | Per-counterparty exposure limit |
| `is_active` | BOOLEAN | ❌ | true | If false, policy not enforced |
| `effective_date` | DATE | ❌ | — | Start date |
| `notes` | TEXT | ✅ | — | Policy description / rationale |
| `created_by` | UUID | ✅ | — | Foreign key → users.id |
| `created_at` | TIMESTAMP | ❌ | now() | Creation time |

**Foreign Keys**: client_id → client.id, entity_id → legal_entity.id, created_by → users.id

**Business Rule**: Only one row with `is_active = TRUE` per entity. Soft-delete older policies.

---

### Table: `investment_cutoff`
**Purpose**: Investment cutoff dates and approval thresholds.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `entity_id` | UUID | ❌ | — | Foreign key → legal_entity.id |
| `cutoff_date` | DATE | ❌ | — | After this date, no new investments allowed |
| `approval_threshold` | NUMERIC(15,2) | ✅ | — | Transactions above this value require CFO approval |
| `notes` | TEXT | ✅ | — | Reason for cutoff |
| `created_at` | TIMESTAMP | ❌ | now() | Creation time |

**Foreign Keys**: client_id → client.id, entity_id → legal_entity.id

**Usage by Agents**:
- Agent 7 (Treasury Continuity): Validates recommendations against cutoff date and approval threshold

---

### Table: `users`
**Purpose**: User credentials and role assignments.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | gen_random_uuid() | Primary key |
| `client_id` | UUID | ❌ | — | Foreign key → client.id |
| `email` | VARCHAR(255) | ❌ | — | Email address (unique; Cognito principal) |
| `cognito_sub` | VARCHAR(255) | ✅ | — | Cognito subject ID (unique; populated at login) |
| `role` | VARCHAR(50) | ❌ | "Viewer" | RBAC role: "Viewer", "Analyst", "TreasuryManager", "CFO" |
| `created_at` | TIMESTAMP | ❌ | now() | User creation time |

**Indexes**: UNIQUE (email), UNIQUE (cognito_sub)

**Foreign Keys**: client_id → client.id

---

## Section B — MongoDB Collections

Core Cash uses MongoDB for analytical results. **AI Backend** owns write; **App Backend** reads.

**Note**: MongoDB collections have no fixed schema enforcement. These are guidelines. Document validation is optional per collection.

---

### Collection: `cash_positions`
**Purpose**: Daily consolidated cash position snapshot.

**Document Shape**:
```json
{
  "_id": ObjectId,
  "client_id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "position_date": "2026-08-24",
  "total_balance_usd": 5000000.0,
  "od_headroom": 500000.0,
  "usable_cash": 4500000.0,
  "accounts": [
    {
      "account_id": "uuid",
      "account_name": "string",
      "currency": "USD",
      "balance": 2000000.0,
      "od_limit": 500000.0,
      "od_utilised": 0.0,
      "include_in_position": true
    }
  ],
  "generated_at": "2026-08-24T10:30:00Z",
  "status": "live"
}
```

**Written by**: Agent 1 (Daily Cash Position)

**Read by**: App Backend (dashboard), Agent 3, Agent 4, Agent 6

**Retention**: No TTL; keep indefinitely for historical analysis

---

### Collection: `forecast_runs`
**Purpose**: 30-day cash flow forecast (Agent 2 output).

**Document Shape**:
```json
{
  "_id": ObjectId,
  "forecast_run_id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "client_id": "uuid",
  "job_id": "uuid",
  "generated_at": "2026-08-24T10:30:00Z",
  "horizon_days": 30,
  "data_status": "partial|blocked",
  "blocked_reason": "OPENING_BALANCE_UNRESOLVED: No bank statement balance found",
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
      "assumptions_applied": ["assumption_id_1", "assumption_id_2"]
    }
  ],
  "assumptions_used": 3,
  "assumptions_skipped": 1,
  "forecast_accuracy_pct": null,
  "notes": ["Confidence bands: ±15% placeholder", "AP/AR actuals not yet wired"]
}
```

**Written by**: Agent 2 (Forecast); updated by Agent 5 (forecast_accuracy_pct)

**Read by**: App Backend (polling), Agent 5, Agent 6

**Retention**: Keep latest 10 per entity; older ones deletable after 90 days

---

### Collection: `agent_2_signals`
**Purpose**: Shortfall detection signal (triggers Agent 3 scoring).

**Document Shape**:
```json
{
  "_id": ObjectId,
  "entity_id": "uuid",
  "client_id": "uuid",
  "job_id": "uuid",
  "shortfall_detected": true,
  "shortfall_day": 1,
  "shortfall_amount_usd": 100000.0,
  "computed_at": "2026-08-24T10:30:00Z"
}
```

**Written by**: Agent 2 (if forecast_rows[d].projected_closing_usd < 0)

**Read by**: Agent 3 (Liquidity Risk) to populate shortfall_pts

**Retention**: No TTL; can be deleted after Agent 3 runs

---

### Collection: `liquidity_risk`
**Purpose**: Risk assessment (cash adequacy, shortfall scoring).

**Document Shape**:
```json
{
  "_id": ObjectId,
  "client_id": "uuid",
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

**Written by**: Agent 3 (Liquidity Risk)

**Read by**: App Backend (dashboard), Agent 4, Agent 6

**Retention**: Keep latest per entity; older ones deletable after 30 days

---

### Collection: `recommendations`
**Purpose**: AI-generated action recommendations (Agent 4 output).

**Document Shape**:
```json
{
  "_id": ObjectId,
  "client_id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "job_id": "uuid",
  "recommendation_count": 3,
  "created_at": "2026-08-24T10:30:00Z",
  "recommendations": [
    {
      "id": "rec_123",
      "what": "Invest USD 500k in money market fund",
      "why": "Excess liquidity; forecast shows +USD 600k 7-day balance",
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
      "override_reason": null,
      "blocked_count": 0,
      "blocked_reasons": []
    }
  ]
}
```

**Written by**: Agent 4 (Action Recommendation)

**Read by**: App Backend (polling, approval flow), Agent 7, Agent 8

**Special Fields**:
- `blocked_count`, `blocked_reasons`: **Internal only — NEVER returned in API responses**
- Populated by Agent 7 (Treasury Continuity) if policy violations detected
- Used to hide blocked recommendations from frontend

**Retention**: Keep latest 5 per entity; older ones deletable after 90 days

---

### Collection: `variance_explanations`
**Purpose**: Why forecast differed from actuals (Agent 5 output).

**Document Shape**:
```json
{
  "_id": ObjectId,
  "client_id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "variance_run_id": "uuid",
  "forecast_run_id": "uuid",
  "job_id": "uuid",
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

**Written by**: Agent 5 (Variance Explanation)

**Read by**: App Backend (polling), Agent 6, frontend (dashboard details)

**Retention**: Keep latest 10 per entity; older ones deletable after 60 days

---

### Collection: `cfo_reports`
**Purpose**: Executive summary for CFO dashboard (Agent 6 output).

**Document Shape**:
```json
{
  "_id": ObjectId,
  "client_id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "report_date": "2026-08-24",
  "executive_summary": "Cash position strong. 3 investment opportunities identified.",
  "top_risks": [
    {
      "rank": 1,
      "risk": "Seasonal outflow spike in Q4",
      "mitigation": "Pre-arrange credit line renewal"
    }
  ],
  "top_recommendations": [
    { "id": "rec_1", "what": "...", "why": "...", "priority": 1 }
  ],
  "forecast_outlook": [
    { "date": "2026-08-25", "projected_closing_usd": 5100000.0, "confidence_band_low_usd": 4335000, "confidence_band_high_usd": 5865000 }
  ],
  "generated_at": "2026-08-24T10:30:00Z"
}
```

**Written by**: Agent 6 (CFO Summary)

**Read by**: App Backend (CFO dashboard), Agent 8, email export

**Retention**: Keep latest 30 per entity; older ones deletable after 365 days

---

### Collection: `daily_briefings`
**Purpose**: Time-series snapshots for email delivery and historical tracking.

**Document Shape**:
```json
{
  "_id": ObjectId,
  "client_id": "uuid",
  "entity_id": "uuid",
  "entity_name": "string",
  "briefing_date": "2026-08-24",
  "briefing_type": "morning|evening",
  "subject": "Core Cash Daily Brief — Aug 24",
  "body": "HTML-formatted briefing",
  "key_metrics": {
    "total_balance_usd": 5000000.0,
    "usable_cash": 4500000.0,
    "risk_level": "Low",
    "pending_recommendations": 3
  },
  "generated_at": "2026-08-24T06:00:00Z"
}
```

**Written by**: Agent 8 (Daily Briefing)

**Read by**: App Backend (email delivery), email service

**Retention**: Keep indefinitely for historical archive

---

## Post-MVP Notes

- **ML Forecast Model**: Agent 2's ±15% confidence bands are placeholders. Post-MVP: implement ARIMA or linear regression on 90-day history.
- **AP/AR Actuals**: Agent 2 currently ignores actual inflows/outflows; uses manual assumptions only. Post-MVP: wire Session 10 parsers.
- **MongoDB TTL Indexes**: Not yet configured. Post-MVP: add TTL policies per retention notes above.
- **Decision Log**: Post-MVP: add decision_log PostgreSQL table (Agent 7 Phase 2) to track policy override rationale.

Next: [API Endpoint Reference →](03-api-reference.md)
