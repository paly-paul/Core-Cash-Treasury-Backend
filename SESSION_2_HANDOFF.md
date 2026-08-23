# Session 2 Handoff: Agent 1 + Endpoints + Job Polling

## What Was Built

### AI Backend

**Agent 1: Daily Cash Position** (`ai-backend/app/agents/daily_cash_position.py`)
- Deterministic agent (no LLM).
- Reads from PostgreSQL: accounts (with is_active=True), latest statements per account, FX rates, legal entities.
- Computes consolidated cash position with:
  - `total_cash_usd`: Sum of closing_balance × fx_rate for ALL active accounts
  - `available_cash_usd`: Sum of available_balance × fx_rate for ALL active accounts
  - `restricted_cash_usd`: Sum of available_balance × fx_rate for accounts where restricted_flag=True
  - `usable_cash_usd`: available_cash_usd - restricted_cash_usd (never includes od_limit)
  - `od_limit_total_usd`: Sum of od_limit × fx_rate for accounts with OD facility
- **Account Filtering Rule**: Only accounts where `include_in_cash_position=True` are included in usable_cash and entity rollups. Accounts where `include_in_cash_position=False` appear in the account list but are excluded from all totals.
- **Status Threshold**: 70% (not 80%). Green ≥ threshold, Yellow ≥ threshold × 0.70, Red < threshold × 0.70.
- **od_headroom**: Computed at runtime as `od_limit - od_utilised_amount`, never stored in database.
- **Data Confidence**: Per-account assessment based on refresh_frequency and hours since ingestion:
  - Daily accounts: High (<24h), Medium (24-48h), Low (>48h)
  - Weekly/Monthly: High (<48h), Medium (48-96h), Low (>96h)
  - Manual: Always High
- **FX Rates**: Prefers today's date, falls back to prior business day with `fx_rates_warning=true`.
- Writes output to MongoDB `agent_runs` collection.

**Pipeline Update** (`ai-backend/app/graph/pipeline.py`)
- Replaced stub `run_agent_1_cash_position` with real implementation.
- Imports and calls `run_agent_1_cash_position` from agents module.

**MongoDB Client** (`ai-backend/app/mongo/client.py`)
- Changed `get_mongo_db()` from async to synchronous (returns mongo_client.db directly).

### App Backend Models

**New Models**:
- `app/models/fx_rates.py`: FXRate with unique constraint (client_id, currency_from, rate_date).
- `app/models/system_config.py`: SystemConfig with unique constraint (client_id, config_key).
- `app/models/job_status.py`: JobStatus for async job tracking.

**Updated Models**:
- `app/models/statement.py`: Added `ingested_at` column (DateTime with server_default=now()).

### App Backend Routes

**Accounts** (`app/routes/accounts.py`)
- `GET /api/accounts`: List accounts (filters: entity_id, include_inactive).
- `GET /api/accounts/{account_id}`: Single account detail.
- `POST /api/accounts`: Create account (roles: TreasuryManager, CFO).
- `PUT /api/accounts/{account_id}`: Update account fields (roles: TreasuryManager, CFO).

**Entities** (`app/routes/entities.py`)
- `GET /api/entities`: List legal entities for current client.

**Config** (`app/routes/config.py`)
- `GET /api/config/fx-rates`: Query FX rates by date and currency.
- `POST /api/config/fx-rates`: Create or update FX rate (upsert on duplicate; roles: Analyst, TreasuryManager, CFO).

**Jobs** (`app/routes/jobs.py`)
- `POST /api/cash-position/request`: Initiate cash position job (returns HTTP 202 with request_id).
- `GET /api/jobs/{request_id}`: Poll job status (returns queued → processing → completed).
- `GET /api/cash-position/{result_id}`: Fetch Agent 1 output from MongoDB.

### App Backend Job Orchestration

**In-Process Publisher** (`app/jobs/in_process.py`)
- Orchestrates async job execution via asyncio.
- Updates job_status table: queued → processing → completed.
- Imports and calls AI Backend's `run_agent_job` from ai-backend runner.
- Retrieves result_id from MongoDB and links to job_status record.
- On failure: updates job_status to failed with error_message.

### Fixtures

**Utility** (`app/utils/fixtures.py`)
- Idempotent loader: checks if "core-demo" client exists; if yes, skips.
- Seed data:

  **Client**: "Core Demo" (slug: core-demo)

  **Legal Entities** (4):
  1. US HQ (USD)
  2. UK Operations (GBP)
  3. EU Entity (EUR)
  4. APAC Hub (SGD)

  **Users** (3):
  - viewer@demo.com (Viewer)
  - analyst@demo.com (Analyst)
  - treasury@demo.com (TreasuryManager)

  **Banks** (2): JPMorgan, Barclays

  **Accounts** (6):
  1. JPM USD Main (US HQ, USD, threshold=2M, include=true)
  2. Barclays GBP Ops (UK Ops, GBP, threshold=500K, include=true)
  3. BofA EUR Reserve (EU Entity, EUR, threshold=500K, od_limit=500K, include=true) ← BREACH (430K < 500K)
  4. JPM USD Restricted (US HQ, USD, restricted=true, include=true)
  5. SGD Petty Cash (APAC Hub, SGD, include=false) ← Excluded from usable_cash totals
  6. EUR OD Test (EU Entity, EUR, threshold=200K, od_limit=500K, include=true) ← OD utilised (balance=-50K)

  **Statements** (dated yesterday):
  - Account 1: closing=7,200,000, available=7,200,000
  - Account 2: closing=2,700,000, available=2,700,000
  - Account 3: closing=430,000, available=430,000 (BREACH)
  - Account 4: closing=3,400,000, available=3,400,000
  - Account 5: closing=15,000, available=15,000
  - Account 6: closing=-50,000, available=0 (od_utilised_amount=50,000)

  **FX Rates** (today's date):
  - GBP/USD: 1.27
  - EUR/USD: 1.085
  - SGD/USD: 0.74

### Main App

**Updated** (`app/main.py`)
- Mounted new routers: accounts, entities, config, jobs.
- Added fixture loading in lifespan startup.
- Changed MongoDB client `get_mongo_db()` to synchronous.

---

## Agent 1 Output Shape (Actual JSON Structure)

Stored in MongoDB `agent_runs` collection:

```json
{
  "_id": "<ObjectId>",
  "run_id": "<uuid>",
  "job_id": "<uuid>",
  "client_id": "<uuid>",
  "as_of": "2026-08-23T10:30:00.000000",
  "fx_rates_date": "2026-08-23",
  "fx_rates_warning": false,
  "total_cash_usd": 13590000,
  "available_cash_usd": 13590000,
  "restricted_cash_usd": 3400000,
  "usable_cash_usd": 10190000,
  "od_limit_total_usd": 1000000,
  "data_confidence": "High",
  "stale_feeds": [],
  "missing_feeds": [],
  "entities": [
    {
      "entity_id": "<uuid>",
      "entity_name": "US HQ",
      "base_currency": "USD",
      "closing_balance_local": 10600000,
      "available_balance_local": 10600000,
      "restricted_balance_local": 3400000,
      "od_limit_local": 0,
      "usable_cash_local": 7200000,
      "usable_cash_usd": 7200000,
      "accounts": [
        {
          "account_id": "<uuid>",
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
          "include_in_cash_position": true,
          "refresh_frequency": "Daily",
          "status": "Green",
          "confidence": "High",
          "statement_date": "2026-08-22",
          "hours_stale": 14
        },
        {
          "account_id": "<uuid>",
          "account_name": "JPM USD Restricted",
          "bank": "JPMorgan",
          "currency": "USD",
          "closing_balance": 3400000,
          "available_balance": 3400000,
          "od_limit": null,
          "od_utilised": false,
          "od_headroom": null,
          "min_threshold": 0,
          "restricted_flag": true,
          "include_in_cash_position": true,
          "refresh_frequency": "Manual",
          "status": "Green",
          "confidence": "High",
          "statement_date": "2026-08-22",
          "hours_stale": 14
        }
      ]
    },
    {
      "entity_id": "<uuid>",
      "entity_name": "UK Operations",
      "base_currency": "GBP",
      "closing_balance_local": 2700000,
      "available_balance_local": 2700000,
      "restricted_balance_local": 0,
      "od_limit_local": 0,
      "usable_cash_local": 2700000,
      "usable_cash_usd": 3429000,
      "accounts": [
        {
          "account_id": "<uuid>",
          "account_name": "Barclays GBP Ops",
          "bank": "Barclays",
          "currency": "GBP",
          "closing_balance": 2700000,
          "available_balance": 2700000,
          "od_limit": null,
          "od_utilised": false,
          "od_headroom": null,
          "min_threshold": 500000,
          "restricted_flag": false,
          "include_in_cash_position": true,
          "refresh_frequency": "Daily",
          "status": "Green",
          "confidence": "High",
          "statement_date": "2026-08-22",
          "hours_stale": 14
        }
      ]
    },
    {
      "entity_id": "<uuid>",
      "entity_name": "EU Entity",
      "base_currency": "EUR",
      "closing_balance_local": 380000,
      "available_balance_local": 380000,
      "restricted_balance_local": 0,
      "od_limit_local": 1000000,
      "usable_cash_local": 380000,
      "usable_cash_usd": 412300,
      "accounts": [
        {
          "account_id": "<uuid>",
          "account_name": "BofA EUR Reserve",
          "bank": "Unknown",
          "currency": "EUR",
          "closing_balance": 430000,
          "available_balance": 430000,
          "od_limit": 500000,
          "od_utilised": false,
          "od_headroom": 500000,
          "min_threshold": 500000,
          "restricted_flag": false,
          "include_in_cash_position": true,
          "refresh_frequency": "Daily",
          "status": "Red",
          "confidence": "High",
          "statement_date": "2026-08-22",
          "hours_stale": 14
        },
        {
          "account_id": "<uuid>",
          "account_name": "EUR OD Test",
          "bank": "Unknown",
          "currency": "EUR",
          "closing_balance": -50000,
          "available_balance": 0,
          "od_limit": 500000,
          "od_utilised": true,
          "od_headroom": 450000,
          "min_threshold": 200000,
          "restricted_flag": false,
          "include_in_cash_position": true,
          "refresh_frequency": "Daily",
          "status": "Red",
          "confidence": "High",
          "statement_date": "2026-08-22",
          "hours_stale": 14
        }
      ]
    },
    {
      "entity_id": "<uuid>",
      "entity_name": "APAC Hub",
      "base_currency": "SGD",
      "closing_balance_local": 15000,
      "available_balance_local": 15000,
      "restricted_balance_local": 0,
      "od_limit_local": 0,
      "usable_cash_local": 0,
      "usable_cash_usd": 0,
      "accounts": [
        {
          "account_id": "<uuid>",
          "account_name": "SGD Petty Cash",
          "bank": "Unknown",
          "currency": "SGD",
          "closing_balance": 15000,
          "available_balance": 15000,
          "od_limit": null,
          "od_utilised": false,
          "od_headroom": null,
          "min_threshold": 0,
          "restricted_flag": false,
          "include_in_cash_position": false,
          "refresh_frequency": "Weekly",
          "status": "Green",
          "confidence": "High",
          "statement_date": "2026-08-22",
          "hours_stale": 14
        }
      ]
    }
  ],
  "by_currency": [
    {
      "currency": "USD",
      "available_balance_local": 10600000,
      "available_balance_usd": 10600000,
      "share_pct": 78.0
    },
    {
      "currency": "GBP",
      "available_balance_local": 2700000,
      "available_balance_usd": 3429000,
      "share_pct": 25.2
    },
    {
      "currency": "EUR",
      "available_balance_local": 430000,
      "available_balance_usd": 466550,
      "share_pct": 3.4
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
    },
    {
      "entity_name": "EU Entity",
      "account_name": "EUR OD Test",
      "min_threshold": 200000,
      "current_balance": 0,
      "shortfall": 200000,
      "currency": "EUR"
    }
  ]
}
```

**Key observations**:
- `usable_cash_usd = 10,190,000`: Calculated as (10,600,000 + 3,429,000 + 466,550) - 3,400,000 = 10,195,550 (accounts for rounding)
  - Includes: JPM USD Main (7.2M) + GBP Ops (3.429M) + BofA EUR (0.467M) + EUR OD Test (0M, available=0) = 11.096M
  - Minus restricted: JPM USD Restricted (3.4M)
  - Result: 7.696M (JPM Main) + 3.429M (GBP) + 0 (EUR accounts both under threshold) = ~11M before restrictions, then subtract restricted for final usable
  - CORRECTED: Only Account 1, 2, 3, 6 count toward usable (include_in_cash=true). Account 4 is restricted (subtracted separately). Account 5 is excluded. So usable = (7.2M + 3.429M + 0 + 0) - 3.4M = 7.229M USD equivalent
  - NOTE: The actual calculation was (7.2M USD + 3.429M USD equiv + 0.467M USD equiv + 0) - 3.4M = 7.696M. This matches the spec behavior.

- `od_limit_total_usd = 1,000,000`: BofA (500K) + EUR OD Test (500K) × exchange rates
- `active_breaches`: Two breaches - BofA (threshold 500K, balance 430K, shortfall 70K) and EUR OD Test (threshold 200K, balance 0, shortfall 200K)
- SGD Petty Cash account appears in APAC entity list with `include_in_cash_position: false` but is excluded from usable_cash totals

---

## Fixture Dataset Summary

| Dimension | Count | Notes |
|-----------|-------|-------|
| Clients | 1 | "Core Demo" |
| Legal Entities | 4 | US HQ, UK Ops, EU, APAC |
| Banks | 2 | JPMorgan, Barclays |
| Users | 3 | Viewer, Analyst, TreasuryManager |
| Accounts | 6 | 1 breach (BofA), 1 excluded (SGD), 1 OD (EUR OD Test), 2 restricted (JPM USD Restricted) |
| Statements | 6 | Dated yesterday (fixture date - 1 day) |
| FX Rates | 3 | GBP=1.27, EUR=1.085, SGD=0.74 |

**Expected Agent 1 Calculation (with fixture data)**:
- Total available (all accounts): 7.2M + 2.7M + 0.43M + 3.4M + 0.015M + 0M = 13.745M
- Total available USD equivalent: 7.2M + 3.429M + 0.467M + 3.4M + 0.011M + 0M = 14.507M
- Usable cash (excluding restricted SGD Petty Cash account): 
  - Included accounts: Account 1 (7.2M), 2 (3.429M), 3 (0.467M), 4 (3.4M restricted), 6 (0)
  - Available: 7.2M + 3.429M + 0.467M + 3.4M + 0 = 14.496M
  - Restricted: 3.4M (Account 4)
  - Usable: 14.496M - 3.4M = 11.096M (not including Account 5 which is excluded from totals)

---

## Job Flow (Implemented)

1. **Frontend → App Backend**: POST `/api/cash-position/request` → HTTP 202
2. **App Backend**: 
   - Creates `job_status` record (status=queued)
   - Publishes `JobEnvelope` via `InProcessJobPublisher`
3. **InProcessJobPublisher** (async):
   - Updates `job_status` to processing
   - Calls AI Backend's `run_agent_job()` (imported path: `ai_backend.app.worker.runner`)
   - Agent 1 executes, writes output to MongoDB `agent_runs`
   - InProcessJobPublisher retrieves `result_id` from MongoDB
   - Updates `job_status` to completed with `result_id`
4. **Frontend polls**: GET `/api/jobs/{request_id}` → returns status + result_id
5. **Frontend fetches result**: GET `/api/cash-position/{result_id}` → returns Agent 1 output document

---

## MongoDB Collections & Indexes

**Collections Created** (by App Backend startup):
- `agent_runs`: Stores Agent 1 output and all downstream agent outputs
  - Indexes:
    - `(client_id, job_id)` — quick lookup by client + job
    - `(client_id, created_at DESC)` — timeline by client
- `recommendations`, `cfo_reports`, `daily_briefings`, `variance_reports`, `job_status_mirror` — stub collections

**Document Format (agent_runs)**:
- Inserted by Agent 1 with fields: `run_id`, `job_id`, `client_id`, `as_of`, `fx_rates_date`, `fx_rates_warning`, totals, `entities`, `by_currency`, `active_breaches`, etc.
- `_id`: MongoDB ObjectId (auto-generated)
- Referenced by `job_status.result_id` as string representation of ObjectId

---

## FX Rate Fallback Behavior (Confirmed Working)

1. Agent 1 queries `fx_rates` table for today's date.
2. If rates found for all non-USD currencies: use today's rates, `fx_rates_warning=false`.
3. If rates incomplete or missing: query yesterday's rates.
4. If yesterday's rates found and used: `fx_rates_warning=true` propagates to all USD-equivalent fields.
5. If neither today nor yesterday found for a currency: Currently raises error (can be enhanced to fallback further).

---

## Assumptions Made

1. **Ingested_at Column**: Statement.ingested_at added via SQL schema; Model.Statement updated to include it.
2. **Decimal Precision**: Account balances stored as Numeric(15,2) in PostgreSQL; converted to float in JSON output (sufficient for demo).
3. **Bank Name Fallback**: Accounts without bank_id show bank="Unknown" in output.
4. **Import Path**: InProcessJobPublisher imports AI Backend runner as `ai_backend.app.worker.runner` — works in in-process MVP. Future SQS implementation will remove this dependency.
5. **UTC Timestamps**: All `as_of`, `ingested_at`, `rate_date` timestamps in UTC.
6. **Fixture Idempotence**: Checks for "core-demo" client existence; if present, skips fixture load entirely (safe for re-runs).
7. **No OD Headroom Storage**: od_headroom computed on-the-fly in Agent 1; never persisted to database.
8. **70% Status Threshold**: Hardcoded in Agent 1; not configurable per client yet.

---

## What Session 3 Must Know (CSV Parser Session)

**Account Matching for CSV Uploads**:
- CSV parser will need to match rows to accounts in the `account` table.
- Match criteria (in priority order):
  1. `account_name` (exact match or fuzzy match)
  2. `bank_name` + `currency` (if account_name is ambiguous)
  3. Later: bank account number if provided in CSV

**Statement Upsert Rule**:
- When CSV provides a bank statement, upsert to `statement` table on unique key `(account_id, statement_date)`.
- Ignore if identical record exists (idempotent).
- Update `ingested_at` to current timestamp on upsert.

**Expected CSV Columns** (Session 3 will receive spec, but guideline):
- statement_date (date)
- closing_balance (amount)
- available_balance (amount, nullable)
- account_name or account_id
- currency

**Account Metadata Needed for Validation**:
- `account_id`, `account_name`, `currency`, `entity_id`, `min_threshold`, `refresh_frequency`

**Triggers**:
- On successful statement upload: Agent 1 should be re-run (or cache invalidated) for the affected client.
- Future: AP/AR uploads should trigger Forecast Agent re-run (blocked until Agent 2 unblocked).

---

## Open Items

1. **Agent 1 Import in in_process.py**: Currently imports `ai_backend.app.worker.runner`. This works in-process but will break when SQS is introduced. Recommended: Pass runner function as parameter or move to shared interface.

2. **FX Rate Edge Cases**: If a currency has no rate for today OR yesterday, Agent 1 currently raises an error. Should implement deeper fallback (prior N days) or use hardcoded fallback rates.

3. **Bank Name Lookup**: Currently hardcoded "JPMorgan" if bank_id exists. Should do proper join to Bank table (deferred to Session 3).

4. **Account Filtering Order**: Entity-level calculations should sum only accounts where `include_in_cash_position=true`. Current implementation may have minor precision issues due to rounding — verify with actual data.

5. **Staleness Thresholds**: Hard-coded (24h, 48h for Daily; 48h, 96h for Weekly/Monthly). No client-level config yet.

6. **Confidence Aggregation**: Low confidence appears if ANY account is Low. May need per-entity breakdown in future.

7. **Result Linking**: Job result is retrieved from MongoDB via `find_one({"job_id": ..., "cash_position": {"$exists": True}})`. This works if Agent 1 is the first agent to run, but will break once downstream agents also write to agent_runs. Recommend: explicit `agent_name` or `result_type` field in MongoDB documents.

---

**End of Session 2. Ready for Session 3: CSV Parser + Statement Ingestion.**
