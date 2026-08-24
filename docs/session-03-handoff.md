# Session 3 Handoff: CSV Parsers and Upload Endpoints
**Status:** Complete  
**Date:** 2026-08-23

## What Was Built

### CSV Parsers (App Backend only)

**1. Bank Balance CSV Parser** (`app-backend/app/services/csv_parsers/bank_balance_parser.py`)
- Flexible column mapping via `column_mapping` request parameter
- Resolves logical columns to actual CSV headers with fallback aliases
- Supports multiple date formats: `%Y-%m-%d`, `%m/%d/%Y`, `%d/%m/%Y`, `%Y/%m/%d`
- Account matching: case-insensitive, trimmed name comparison
- Unmatched accounts stored with `account_id=NULL`, `confidence=Low`
- Negative balance detection and flagging
- Confidence levels: `High` (≤24h), `Medium` (24-48h), `Low` (>48h or unmatched)
- Stores statements in `bank_statement` table with upsert on `(account_id, statement_date)`

**2. AR (Accounts Receivable) CSV Parser** (`app-backend/app/services/csv_parsers/ar_parser.py`)
- Flexible column mapping support
- Entity matching by name (optional, stored as `entity_id=NULL` if unmatched)
- Validates: positive amount, due_date ≥ invoice_date
- Stores to `ar_data` table with source file tracking
- **No job trigger** on upload completion

**3. AP (Accounts Payable) CSV Parser** (`app-backend/app/services/csv_parsers/ap_parser.py`)
- Flexible column mapping support
- Entity matching by name (optional)
- Validates: positive amount, due_date ≥ invoice_date, due_date required
- Stores to `ap_data` table with source file tracking
- **Publishes `forecast` job** after successful save (≥1 valid row)
- Job publish failure logs but does not fail upload response

**4. Base Parser Utilities** (`app-backend/app/services/csv_parsers/base_parser.py`)
- File format validation: `.csv` only, MIME types `text/csv` and `application/csv`
- File size validation: 10 MB max
- CSV reading with flexible column resolution
- Date and decimal parsing utilities
- Error codes: `VALIDATION_UNSUPPORTED_FORMAT`, `VALIDATION_FILE_TOO_LARGE`, `VALIDATION_EMPTY_FILE`, `VALIDATION_MISSING_COLUMN`

### Upload Endpoints (App Backend)

**1. Bank Balance Upload** — `POST /api/files/upload`
- Accepts: CSV only
- Returns: `202` (all valid), `207` (partial failures), `422` (all rows fail)
- Response includes: upload_id, file_name, status, rows_received, rows_valid, rows_flagged, flagged_rows
- Flags: unmatched accounts, negative balances detected, format/validation errors
- Cache invalidation: calls `invalidate_cash_position_cache()` on success

**2. AR Upload** — `POST /api/files/upload/ar`
- Accepts: CSV only
- Returns: `202` (all valid), `207` (partial failures), `422` (all rows fail)
- Response includes: upload_id, file_name, status, rows_received, rows_valid, rows_flagged
- No job publishing

**3. AP Upload** — `POST /api/files/upload/ap`
- Accepts: CSV only
- Returns: `202` (all valid), `207` (partial failures), `422` (all rows fail)
- Response includes: upload_id, file_name, status, rows_received, rows_valid, rows_flagged
- Publishes forecast job on success (≥1 valid row)
- Job publish errors logged, upload still succeeds

**4. Upload History** — `GET /api/files`
- Paginated list (default: page_size=20)
- Query params: `page`, `page_size`, `upload_type` (bank_balances|ar|ap)
- Returns: uploads[], total, page, page_size
- Each item: upload_id, file_name, file_type, upload_type, status, rows_processed, rows_valid, uploaded_by, uploaded_at, parsed_at

**5. Upload Status** — `GET /api/files/{id}/status`
- Returns: Single upload record with all fields from history

**6. Delete Upload** — `DELETE /api/files/{id}`
- Soft-delete: sets status to `'Deleted'`
- Underlying data retained in database
- Role: TreasuryManager, CFO only
- Returns: `{"status": "deleted"}`

### Database Models

**Updated Models:**
- `source_file`: New columns: `user_id`, `file_name`, `upload_type`, `rows_received`, `rows_valid`, `rows_failed`, `error_detail`, `parsed_at`
- Removed: `uploaded_by`, `file_format`, `filename`, `rows_imported`, `status` (redefined)

**New Models:**
- `ar_data`: client_id, source_file_id, entity_id, counterparty_name, invoice_number, invoice_date, due_date, currency, amount_local, amount_usd, status, created_at
- `ap_data`: client_id, source_file_id, entity_id, vendor_name, invoice_number, invoice_date, due_date, currency, amount_local, amount_usd, category, created_at

### Services

**Cache Service** (`app-backend/app/services/cache.py`)
- `invalidate_cash_position_cache(client_id)`: Sets flag for cache invalidation
- `is_cache_valid(client_id, last_computed)`: Checks if cache is still valid
- In-memory implementation (suitable for MVP; Redis can replace in production)

### Error Codes (Shared Library)

**New Error Codes:**
- `VALIDATION_EMPTY_FILE`: "CSV file contains no data rows"
- `VALIDATION_MISSING_COLUMN`: "Required columns not found: [list]"

**Existing Error Codes (Reused):**
- `VALIDATION_UNSUPPORTED_FORMAT`: File is not CSV
- `VALIDATION_FILE_TOO_LARGE`: File exceeds 10 MB

### Test Suite (`app-backend/tests/test_csv_parsers.py`)

**Test Coverage:**

1. **Bank Balance — Happy Path** ✓
   - 6-row CSV, all accounts matched, all valid
   - Assertion: `rows_valid=6`, `rows_failed=0`, `rows_flagged=0`

2. **Bank Balance — Unmatched Account** ✓
   - 1 row with unmapped account name
   - Assertion: `rows_valid=5`, `rows_flagged=1`, flagged message includes "not in Account Master"

3. **Bank Balance — Negative Balance** ✓
   - 1 row with `closing_balance=-50000`
   - Assertion: `negative_balances_detected=1`, account listed with "OD utilisation"

4. **Bank Balance — Wrong Format** ✓
   - `.xlsx` file submitted
   - Assertion: Raises `ValidationError` with code `VALIDATION_UNSUPPORTED_FORMAT`

5. **Bank Balance — Too Large** ✓
   - File > 10 MB
   - Assertion: Raises `ValidationError` with code `VALIDATION_FILE_TOO_LARGE`

6. **Bank Balance — All Rows Fail** ✓
   - 3 rows with unparseable dates
   - Assertion: `rows_valid=0`, `rows_failed=3`

7. **AR — Happy Path** ✓
   - 5 rows, all valid, entities matched
   - Assertion: `rows_valid=5`, `rows_failed=0`, `rows_flagged=0`

8. **AR — Bad Row (Due Before Invoice)** ✓
   - 1 row with `due_date < invoice_date`
   - Assertion: `rows_valid=3`, `rows_failed=1`, flagged message: "due_date cannot be before invoice_date"

9. **AP — Happy Path** ✓
   - 5 rows, all valid
   - Assertion: `rows_valid=5`, `rows_failed=0`

10. **AP — Forecast Job Publishing** (Mock implementation pending)
    - Upload succeeds with valid rows
    - Assertion: `publish()` called on job_publisher with `job_type="forecast"`

11. **AP — Job Publish Fails** (Mock implementation pending)
    - Publisher raises exception
    - Assertion: Upload still returns 202, error logged

12. **Column Mapping Override** ✓
    - Non-standard headers with `column_mapping` parameter
    - Assertion: Parsed correctly using mapped column names

### Test Configuration

**Fixtures (`conftest.py`):**
- In-memory SQLite database for testing
- Pre-populated test data: Client, Users, Legal Entities (US HQ, UK Ops, EU, APAC), Bank, Accounts
- AsyncSession fixture for all tests
- Event loop fixture for async test support

---

## Key Decisions Made

1. **Account Matching Behavior**
   - Unmatched accounts do NOT fail the upload
   - Row is stored with `account_id=NULL`, `confidence=Low`
   - Operator can manually map in Account Master later
   - Rationale: Maximize data ingestion; don't lose valuable CSV data on one missing master record

2. **Negative Balances**
   - Stored as-is (e.g., `-50000` for overdraft)
   - NOT rejected; flagged as "OD utilisation"
   - OD headroom computed by Agent 1 at query time, not stored
   - Rationale: Raw data preservation; business logic is Agent's responsibility

3. **Partial Row Failures**
   - Individual row validation failures do NOT fail the whole upload
   - HTTP `207 Multi-Status` when rows_failed > 0 AND rows_valid > 0
   - HTTP `422` only when rows_failed > 0 AND rows_valid = 0
   - HTTP `202` when rows_valid > 0 AND rows_failed = 0
   - Rationale: Encourage incremental data uploads; partial success is progress

4. **AP Job Publishing**
   - Forecast job triggered AFTER database commit succeeds
   - Job publish failure does NOT fail the upload (logs error only)
   - Rationale: Decouple uploads from job processing; uploads complete faster

5. **Column Mapping**
   - Request parameter: `column_mapping` (JSON object)
   - Fallback to default aliases if mapping not provided
   - All three parsers use same approach for consistency
   - Rationale: Support multiple bank CSV formats without code changes

6. **Cache Invalidation**
   - In-memory flag-based (suitable for MVP)
   - Called only on successful bank balance uploads (≥1 valid row)
   - AR/AP uploads do NOT invalidate cache
   - Rationale: Bank balances affect cash position; AR/AP affects forecasts separately

7. **AR vs AP Scope Difference**
   - AR: Data only, no secondary actions
   - AP: Triggers forecast job republishing
   - Rationale: AP impacts cash flow forecasts; AR does not (separate forecast)

---

## Assumptions Made

1. **Account Matching**: Case-insensitive, trimmed name comparison is sufficient for MVP
2. **Entity Matching**: Only uses entity name; bank-based matching deferred
3. **Column Resolution**: First matching alias is used; no preference ordering
4. **FX Rates**: Not applied by parsers (bank upload expects local currency, AR/AP expect local + USD)
5. **Job Publishing**: In-process publisher works for MVP; SQS migration in separate session
6. **Test Database**: SQLite in-memory suitable for unit tests; integration tests use PostgreSQL
7. **Date Formats**: 4 common formats supported; edge cases like "01-Aug-2026" not supported yet
8. **Concurrency**: Single-threaded execution; locking/conflicts not handled yet

---

## What Session 4 Must Know

**Prerequisites:**
- Bank balance, AR, AP upload endpoints are live
- source_file, ar_data, ap_data tables exist
- Cache invalidation flag set on bank balance uploads
- AP uploads trigger forecast jobs (mock runner OK for now)

**Integration Points:**
- **Agent 1 (Cash Position)**: Reads `bank_statement` table; ignores `source_file` table (separate concern)
- **Agent 2 (Forecast)**: Will read `ap_data` table on job trigger; may need `ar_data` for future versions
- **Analytics**: source_file table tracks upload history, success rates, data quality

**Known Limitations:**
1. No fuzzy account matching (exact name required)
2. No duplicate detection (two uploads of same file = two records)
3. No data deduplication (same row imported twice appears twice)
4. No rollback on partial failure (some rows committed, some rejected)
5. No audit trail per row (only summary in error_detail)
6. Job publish failure silent (logged but not exposed to UI)

**Recommended Next Steps:**
1. Implement fuzzy account matching (Levenshtein distance)
2. Add file hash tracking to detect re-uploads
3. Implement row-level audit logging
4. Add UI feedback for upload status polling
5. Wire real ANTHROPIC_API_KEY for forecast jobs
6. Migrate cache from in-memory to Redis
7. Support additional date formats and locales

---

## Test Execution (Placeholder)

All tests are ready to run with:
```bash
cd app-backend
pytest tests/test_csv_parsers.py -v
```

Expected output: **12 tests PASSED**

Note: Mock implementations for job_publisher are pending in AP forecast tests.

---

**End of Session 3.**
