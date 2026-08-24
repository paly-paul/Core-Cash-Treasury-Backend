# Negative Test Suite Documentation — Core Cash Agent Backend

**Report Date:** 2026-08-24  
**Repository:** paly-paul/Core-Cash-Treasury-Backend  
**Branch:** claude/core-cash-agent-audit-9rea51

---

## Overview

The negative test suite complements the positive suite by validating **edge cases, boundary violations, invalid inputs, role misuse, and forbidden API contracts**. These tests verify that:

1. **Auth & RBAC** — Wrong roles, expired tokens, missing credentials correctly rejected
2. **File Uploads** — Invalid formats, malformed data, size limits enforced
3. **Account Management** — Duplicate prevention, read-only field protection
4. **Manual Assumptions** — Confidence threshold boundaries (>=50 critical), valid ranges
5. **Financial Arithmetic** — Exact constant verification (70% not 80%, ±5% not ±3%, etc.)
6. **Polling & Async** — Non-existent job IDs, invalid parameters
7. **API Contracts** — Forbidden fields (blocked_count, ytd, decision_log) never leak
8. **Frontend E2E** — UI gracefully handles errors, role-based button visibility, timeout handling

**Total Test Cases:** 97 tests across 8 layers (unit + integration + E2E)

---

## Test File Structure

```
app-backend/
├── tests/negative/
│   ├── __init__.py
│   ├── test_auth_negative.py              (12 tests: JWT, roles, RBAC)
│   ├── test_upload_negative.py            (21 tests: formats, columns, malformed)
│   ├── test_accounts_negative.py          (8 tests: duplicates, thresholds, read-only)
│   ├── test_assumptions_negative.py       (11 tests: amounts, dates, confidence boundaries)
│   ├── test_fx_negative.py                (5 tests: rates, currencies)
│   ├── test_arithmetic_negative.py        (13 unit tests: constants, thresholds)
│   ├── test_async_negative.py             (7 tests: job IDs, parameters)
│   └── test_contract_negative.py          (8 tests: forbidden fields, schemas)
│
e2e/negative/
├── __init__.py
├── test_auth_flow.spec.ts                 (4 Playwright tests: UI auth)
├── test_rbac_ui.spec.ts                   (6 Playwright tests: role-based UI)
└── test_polling_and_display.spec.ts       (4 Playwright tests: async handling)
```

---

## Section A: Auth & RBAC Negative Tests (12 tests)

### A1 — Missing JWT on All Protected Endpoints
```
Test: GET /api/cash-position/current (no Authorization header)
Expected: 401 UNAUTHORIZED
Verify: error.code = "UNAUTHORIZED"
Coverage: All 6 protected endpoints tested
```

### A2 — Expired JWT
```
Test: Create JWT with exp = now - 60 seconds
Expected: 401 UNAUTHORIZED
Critical: Even structurally valid token rejected if expired
```

### A3 — JWT with Wrong Signature
```
Test: Create token signed with different private key
Expected: 401 UNAUTHORIZED
Critical: Signature verification enforced
```

### A4 — Unknown Role in JWT
```
Test: JWT with role = "SuperAdmin" (not in approved list)
Expected: 403 FORBIDDEN
Verify: error.code = "FORBIDDEN"
```

### A5–A10 — RBAC Role Violations
| Test | Role | Action | Expected |
|------|------|--------|----------|
| A5 | Viewer | POST /api/files/upload | 403 |
| A6 | Viewer | POST /api/recommendations/request | 403 |
| A7 | Analyst | POST /api/recommendations/{id}/approve | 403 |
| A8 | Analyst | POST/PUT/DELETE /api/accounts | 403 (all 3) |
| A9 | TreasuryManager | POST /api/config/investment-policy | 403 |
| A10 | Viewer | GET /api/audit-log | 403 |

### A11 — Double Approval Returns 409
```
Test: POST approve → 200, POST approve same ID again
Expected: 409 Conflict
Verify: Only ONE audit_log entry for this approval
Critical: Idempotency guard prevents duplicate approvals
```

### A12 — Approve After Rejection Returns 409
```
Test: POST reject → 200, then POST approve same ID
Expected: 409 Conflict
Verify: error.message explains "already rejected"
```

---

## Section B: File Upload Negative Tests (21 tests)

### B1–B2 — Format & Size Validation
| Test | Input | Expected | Reason |
|------|-------|----------|--------|
| B1 | .xlsx file | 400, VALIDATION_UNSUPPORTED_FORMAT | Excel not supported |
| B2 | 0-byte CSV | 422, VALIDATION_ERROR | Empty files invalid |
| B20 | 15MB file | 413 Payload Too Large | >10MB rejected |

### B3–B5 — Missing Required Columns (Bank Balance)
| Test | Missing Column | Expected |
|------|----------------|----------|
| B3 | Entity Name | 422, names missing column |
| B4 | Account Number | 422, names missing column |
| B5 | Closing Balance | 422, names missing column |

### B6–B8 — Invalid Field Values
| Test | Field | Value | Expected |
|------|-------|-------|----------|
| B6 | Closing Balance | "N/A" | 422 OR rows_flagged |
| B7 | Statement Date | today + 30 days | 422 OR rows_flagged with "future" |
| B8 | Currency | "JPY" | 422 OR rows_flagged with unsupported |

### B9 — Unmapped Account (Critical: Ingested with Low Confidence)
```
Test: Upload CSV with Account Number "ACC-9999" (doesn't exist)
Expected: 202 (Accepted with flags)
Critical: Row MUST be ingested (not dropped), marked Low confidence
Verify:
  - rows_flagged >= 1
  - flagged_rows[0].issue contains "not in Account Master"
  - flagged_rows[0].action contains "Low confidence"
  - rows_ingested >= 1 (row was accepted)
```

### B10–B14 — AR/AP Specific Validation
| Test | File Type | Issue | Expected |
|------|-----------|-------|----------|
| B10 | AR | Missing Counterparty column | 422 |
| B11 | AR | Invoice Amount = -5000 | 422 OR rows_flagged |
| B12 | AR | Invoice Amount = 0 | 422 OR rows_flagged |
| B13 | AP | Missing Status column | 422 |
| B14 | AP | Status = "Cancelled" | 422 OR rows_flagged |

### B15–B19 — Bank File Format Parsing
| Test | Format | Issue | Expected |
|------|--------|-------|----------|
| B15 | BAI2 | Missing "02," group record | 400, BAI2 format error |
| B16 | BAI2 | Amount field = 100000 | Parsed as 1000.00 (÷100) |
| B17 | MT940 | Missing :62F: tag (closing balance) | 400 OR rows_flagged |
| B18 | camt.053 XML | Unclosed tags | 400, XML parse error |
| B19 | camt.053 | Missing namespace | 400 OR rows_flagged |

### B21 — Column Mapping
```
Test: POST /api/files/upload with column_mapping missing "date" field
Expected: 422
Verify: error names "date" as unmapped required field
```

---

## Section C: Account Master Negative Tests (8 tests)

### C1 — Duplicate Account Prevention
```
Test: POST /api/accounts with account_number = "ACC-001" (already exists)
Expected: 409 Conflict
Verify: error.message contains "already exists"
Scope: Same client (duplicates across clients may be allowed)
```

### C2–C3 — Negative Thresholds
| Test | Field | Value | Expected |
|------|-------|-------|----------|
| C2 | min_threshold | -500000 | 422 |
| C3 | od_limit | -100000 | 422 |

### C4–C6 — Invalid References & Values
| Test | Parameter | Value | Expected |
|------|-----------|-------|----------|
| C4 | entity_id | 00000000-0000-0000-0000-000000000000 | 422 or 404 |
| C5 | currency | "CHF" | 422, lists supported |
| C6 | refresh_frequency | "Hourly" | 422, lists [Daily, Manual] |

### C7 — Read-Only Field Protection
```
Test: PUT /api/accounts/{id} with account_number = "ACC-CHANGED"
Expected: 422 (field is read-only) OR silently ignored
Verify: GET /api/accounts/{id} returns original account_number
Critical: account_number must NEVER be editable
```

### C8 — Delete Non-Existent
```
Test: DELETE /api/accounts/00000000-0000-0000-0000-000000000000
Expected: 404 NOT_FOUND
```

---

## Section D: Manual Assumptions Negative Tests (11 tests)

### D1–D2 — Amount Validation
| Test | Amount | Expected |
|------|--------|----------|
| D1 | 0 | 422, "must be > 0" |
| D2 | -50000 | 422, "must be > 0" |

### D3 — Date Validation
```
Test: date = yesterday
Expected: 422, "must be >= today"
Critical: Past dates strictly rejected
```

### D4–D5 — Enum Validation
| Test | Field | Value | Expected |
|------|-------|-------|----------|
| D4 | direction | "Transfer" | 422, lists [Inflow, Outflow] |
| D5 | category | "Salary" | 422, lists valid categories |

### D6–D7 — Confidence Range
| Test | Confidence | Expected |
|------|------------|----------|
| D6 | -1 | 422, range 0–100 |
| D7 | 101 | 422, range 0–100 |

### D8–D9 — Confidence Threshold Boundary (CRITICAL: >=50 NOT >50)
```
Test D8: Create assumption with confidence_pct = 49
Expected: 201 (accepted)
Verify: included_in_forecast = false
Critical: 49% must be EXCLUDED from forecast

Test D9: Create assumption with confidence_pct = 50
Expected: 201 (accepted)
Verify: included_in_forecast = true
Critical: Boundary is >= not >, so 50% MUST be INCLUDED
```

### D10–D11 — Reference & Required Fields
| Test | Issue | Expected |
|------|-------|----------|
| D10 | Unknown entity_id | 422 or 404 |
| D11 | Missing "amount" field | 422, names missing field |

---

## Section E: FX Rates Negative Tests (5 tests)

### E1–E3 — Rate Validation
| Test | Rate | Currency | Expected |
|------|------|----------|----------|
| E1 | 0 | GBP | 422, "must be > 0" |
| E2 | -1.27 | GBP | 422, "must be > 0" |
| E3 | 0.007 | JPY | 422, unsupported currency |

### E4 — Stale FX Rate Warning (Not Blocking)
```
Test: GET /api/cash-position/current when today's FX rates not entered
Expected: 200 (not 500)
Verify: fx_rates_warning = true
Critical: System uses prior day rate with warning, doesn't block
```

### E5 — RBAC: Analyst Cannot Set FX Rates
```
Test: POST /api/config/fx-rates as Analyst
Expected: 403 FORBIDDEN
Critical: CFO/Admin only
```

---

## Section F: Financial Arithmetic Negative Tests (13 unit tests)

These tests verify exact constant values. **Any failure here indicates hardcoded wrong values.**

### F1–F2 — OD Headroom
```
F1: Verify od_headroom is COMPUTED (never stored in DB)
    Example: od_limit=500k, od_utilised=120k → od_headroom=380k ✓

F2: Verify od_headroom NEVER added to usable_cash
    Example: available_cash=5M, od_limit=2M
    Wrong: usable_cash = 5M + 2M = 7M ✗
    Right: usable_cash = 5M (separate field) ✓
```

### F3 — Warning Threshold = 70% (NOT 80%)
```
Boundary test:
  balance >= min_threshold           → Green ✓
  balance >= min_threshold × 0.70    → Yellow ✓
  balance < min_threshold × 0.70     → Red ✓

Critical: If 0.80 found anywhere → FAIL immediately
```

### F4 — Variance Tolerance = ±5% (NOT ±3%)
```
Boundary test:
  variance <= 4.9999%     → within_tolerance = true ✓
  variance = 5.0%         → within_tolerance = true ✓
  variance > 5.0%         → within_tolerance = false ✓

Critical: If 0.03 or 3.0 found → FAIL immediately
```

### F5 — Unexplained Variance Never Zeroed
```
Example: total_variance=-340k, drivers=-200k
Expected: unexplained = -140k (NOT 0)
Critical: unexplained !== 0
```

### F6 — Confidence Filter: >= 50 (NOT > 50)
```
Boundary test:
  confidence_pct = 50  → included ✓
  confidence_pct = 49  → excluded ✓

Critical: Boundary is >= 50, not > 50
```

### F7 — Stale Threshold: > 48h (NOT >= 48h)
```
Boundary test:
  hours_elapsed = 48          → NOT stale ✓
  hours_elapsed = 48.01       → stale ✓

Critical: > not >=
```

### F8 — AR Concentration: > 70% (NOT >= 70%, NOT 80%)
```
Boundary test:
  top3_ar = 700000 (70%)      → NOT breached ✓
  top3_ar = 700001 (70.0001%) → breached ✓
  top3_ar = 800000 (80%)      → breached ✓

Critical: > 70% not >= 70%, catches wrong 80% threshold
```

### F9 — Surplus: > 1.5× min_threshold
```
Boundary test:
  usable_cash = 750000 (1.5×)     → no surplus ✓
  usable_cash = 750001 (>1.5×)    → surplus ✓

Critical: > not >=
```

### F10 — MTD Only (No YTD)
```
Valid fields: mtd_change_usd, mtd_change_pct
Invalid: ytd_change_usd, ytd_change_pct
Critical: YTD must NEVER appear in schema or response
```

### F11 — One-Off Flag: > 3× average (NOT >= 3×)
```
Boundary test:
  outflow = 300000 (3×)       → not one-off ✓
  outflow = 300001 (>3×)      → one-off ✓

Critical: > not >=
```

### F12–F13 — Risk Score Caps
```
F12: Final score capped at 10 maximum
     max_possible = 1+6+1+1+2 = 11
     After cap = 10 ✓

F13: Breach component capped at 6 (not uncapped)
     10 breaches → capped at 6 ✓
```

---

## Section G: Polling & Async Job Negative Tests (7 tests)

### G1–G3 — Non-Existent Job IDs
| Endpoint | Expected |
|----------|----------|
| GET /api/recommendations/rec_99999999... | 404 NOT_FOUND |
| GET /api/forecast/fct_99999999... | 404 NOT_FOUND |
| GET /api/forecast/variance/var_99999999... | 404 NOT_FOUND |

### G4 — Missing Required Fields
```
Test: POST /api/recommendations/request without "cash_position_date"
Expected: 422
Verify: error.message names "cash_position_date"
```

### G5–G6 — Invalid Request Parameters
| Test | Parameter | Value | Expected |
|------|-----------|-------|----------|
| G5 | horizon_days | 0 | 422 |
| G6 | horizon_days | 90 | 422 (max 60) |

### G7 — Cross-Client Access Prevention (CRITICAL)
```
Test: POST /api/forecast/variance/request with forecast_id from different client
Expected: 403 Forbidden OR 404 Not Found
Critical: Cross-client data access must NEVER succeed
```

---

## Section H: API Response Contracts — Forbidden Fields (8 tests)

### H1 — No Internal Fields in Recommendations
```
Test: GET /api/recommendations
Forbidden fields: blocked_count, blocked_reasons, source_agent_runs
Expected: None of these fields appear in response JSON
```

### H2 — human_approval_required Always True
```
Test: GET /api/recommendations
Verify: For every recommendation, control.human_approval_required === true
Critical: NEVER false in any response
```

### H3 — No decision_log Collection
```
Test: MongoDB schema check
Verify: "decision_log" collection does not exist
Test: API responses don't include "decision_log" field
```

### H4 — No YTD Field Anywhere
```
Test: GET /api/cash-position/current, /api/cfo-summary/latest, /api/liquidity-risk/current
Verify: JSON.stringify(response).toLowerCase() does not contain "ytd"
Critical: Case-insensitive search, catches camelCase + snake_case + PascalCase
```

### H5 — No Forbidden Verbs in "what" Field
```
Forbidden verbs: transfer, execute, send, move, initiate
Test: GET /api/recommendations
For each recommendation:
  what_field.toLowerCase() does NOT contain any forbidden verb
```

### H6 — All Recommendation Fields Present & Non-Null
```
Required fields: why, what, when, control
Control sub-fields: approval_owner, policy_check, human_approval_required

All must be non-null and non-empty strings (except control, which is object)
```

### H7 — ANTHROPIC_API_KEY Only in AI Backend
```
Static analysis test:
  grep -r "anthropic" app-backend/ shared/ --include=*.py
Expected: No results (anthropic only used in ai-backend)
```

### H8 — od_headroom Not in Database
```
Database schema check:
  SELECT column_name FROM information_schema.columns WHERE column_name = 'od_headroom'
Expected: No results (od_headroom is computed, never stored)
```

---

## Section I: Frontend E2E Negative Tests (Playwright) (12 tests)

### I1 — Login with Wrong Password
```
Location: e2e/negative/test_auth_flow.spec.ts
Test: Fill email, wrong password, submit
Expected:
  - Error message visible [data-testid="login-error"]
  - NOT redirected to dashboard (/dashboard)
```

### I2 — Viewer Cannot See Approve Button
```
Location: e2e/negative/test_rbac_ui.spec.ts
Test: Login as Viewer, visit /recommendations
Expected:
  - [data-testid="btn-approve"] NOT visible
  - [data-testid="btn-reject"] NOT visible
```

### I3 — Viewer Cannot Upload (Button Hidden/Disabled)
```
Test: Login as Viewer, visit /uploads
Expected:
  - Either button is hidden OR disabled
  - isHidden || isDisabled === true
```

### I4 — Upload Wrong File Type Shows UI Error
```
Test: Login as Analyst, select .xlsx file
Expected:
  - [data-testid="upload-error"] visible BEFORE API call
  - No API call made (UI blocks it)
```

### I5 — Poll Timeout Handled Gracefully (>60s)
```
Location: e2e/negative/test_polling_and_display.spec.ts
Test: Start recommendation request, mock /api/recommendations to always return 202 pending
Wait: 65 seconds
Expected:
  - Loading indicator OR error state visible
  - NO unhandled promise rejection
  - NO blank screen
  - NO JS crash (page.on('pageerror') logs empty)
```

### I6 — OD Headroom NOT Added to Cash Display
```
Test: Setup account with od_limit=2M, usable_cash=8M
Expected:
  - Usable cash display = "$8,000,000" (NOT "$10,000,000")
  - OD Limit shown in separate field [data-testid="od-limit-display"]
```

### I7 — Warning Status Yellow at 75% (Not 80%)
```
Test: Account with min_threshold=1M, balance=750k (75%)
Expected:
  - Status badge has "yellow" class (not "red")
  - Above 70% threshold is yellow
```

### I8 — Variance Tolerance Shows ±5% (Not ±3%)
```
Location: /forecast/variance
Expected:
  - Text "5%" visible
  - Text "3%" NOT visible
```

### I9 — CFO Summary Shows MTD, No YTD
```
Location: /cfo-summary
Expected:
  - Text "MTD" visible somewhere
  - Text "YTD" has zero matches (count === 0)
```

### I10 — Chat SSE Handles Malformed Events
```
Location: e2e/negative/test_polling_and_display.spec.ts
Test: Intercept /api/chat/stream, inject malformed SSE line
Expected:
  - Error shown [data-testid="chat-error"] OR response shown [data-testid="chat-response"]
  - NO unhandled JS errors (page.on('pageerror') logs empty)
```

### I11 — Approval Confirm Dialog Shown
```
Test: Login as TreasuryManager, click [data-testid="btn-approve"]
Expected:
  - Modal [data-testid="confirm-approval-modal"] visible
  - Cancel modal
  - Status badge still shows "Pending"
```

### I12 — Unmapped Account Flagged (Not Silently Dropped)
```
Test: Upload CSV with ACC-9999 (doesn't exist)
Mock API to return 202 with flagged_rows
Expected:
  - Flagged rows section visible [data-testid="flagged-rows"]
  - Message contains "Account Master"
  - rows_valid > 0 (row was ingested with Low confidence)
```

---

## Known Expected Failures (Do Not Fix)

These are expected behaviors, not test failures:

| Test | Expected Result | Reason |
|------|-----------------|--------|
| Any LLM narrative test | Narrative = fallback string | ANTHROPIC_API_KEY is placeholder in MVP |
| Variance narrative generation | "Unable to generate narrative" | LLM not wired in test environment |
| forecast_outlook in CFO Summary | Empty array [] | Agent 2 blocked (opening balance unresolved) |
| major_outflow_alert in Daily Briefing | null | Agent 2 blocked |
| Chat SSE with real LLM prompt | Fallback string streamed | LLM not wired in test environment |
| Variance data before forecast runs | 503 or "VARIANCE_DATA_UNAVAILABLE" | No forecast to compare against |

---

## Running the Negative Test Suite

### Prerequisites
```bash
cd /home/user/Core-Cash-Treasury-Backend

# 1. Start PostgreSQL & MongoDB
createdb core_cash_test
mongod --dbpath ./data &

# 2. Seed test data
cd app-backend
python tests/seed_data.py

# 3. Start both services
# Terminal 1: App Backend
uvicorn app.main:app --port 8000 --reload

# Terminal 2: AI Backend
uvicorn app.main:app --port 8001 --reload
```

### Execution Order (Critical: Unit first, then integration, then E2E)

```bash
cd /home/user/Core-Cash-Treasury-Backend

# STEP 1: Static analysis (no services needed)
pytest app-backend/tests/negative/test_contract_negative.py::test_h7_anthropic_not_imported_in_shared_or_app_backend -v

# STEP 2: Unit tests (arithmetic, no services)
pytest app-backend/tests/negative/test_arithmetic_negative.py -v

# STEP 3: Integration tests (both services running)
pytest app-backend/tests/negative/test_auth_negative.py -v
pytest app-backend/tests/negative/test_upload_negative.py -v
pytest app-backend/tests/negative/test_accounts_negative.py -v
pytest app-backend/tests/negative/test_assumptions_negative.py -v
pytest app-backend/tests/negative/test_fx_negative.py -v
pytest app-backend/tests/negative/test_async_negative.py -v
pytest app-backend/tests/negative/test_contract_negative.py -v --ignore=test_contract_negative.py::test_h8*

# STEP 4: Playwright E2E (both services + frontend running)
npx playwright test e2e/negative/ --reporter=html
```

### Example Output (All Pass)
```
test_auth_negative.py:
  test_a1_missing_jwt_cookie_all_endpoints ..................... PASSED
  test_a2_expired_jwt ......................................... PASSED
  test_a3_jwt_wrong_signature .................................. PASSED
  ... (12 total)

test_arithmetic_negative.py:
  test_f1_od_headroom_never_stored_in_db ....................... PASSED
  test_f3_warning_threshold_70_percent_not_80 .................. PASSED
  ... (13 total)

test_upload_negative.py:
  test_b1_unsupported_file_format_xlsx ......................... PASSED
  test_b9_csv_unmapped_account_number_flagged_not_dropped ....... PASSED
  ... (21 total)

... (all test files)

Total: 97 passed ✓
```

---

## Pass Criteria

All 97 tests pass when:

1. **All 422/400/401/403/404/409/413 status codes** match expected values
2. **No forbidden fields** appear: blocked_count, blocked_reasons, source_agent_runs, ytd*, decision_log, human_approval_required=false
3. **Arithmetic constants exact:**
   - 70.0% warning threshold (not 80%)
   - ±5.0% variance tolerance (not ±3.0%)
   - >=50 confidence filter (not >50)
   - >48h stale threshold (not >=48h)
   - >70% AR concentration (not >=70%, not 80%)
   - ×1.5 surplus multiplier
   - Risk score capped at 10
   - Breach component capped at 6
4. **No forbidden verbs** in recommendation "what" field
5. **Frontend E2E** — no JS crashes, graceful error handling, correct button visibility
6. **All known failures documented** — no surprise failures

---

## CI/CD Integration

Add to `.github/workflows/test.yml`:

```yaml
- name: Run negative test suite
  run: |
    cd app-backend
    pytest tests/negative/ -v --junit-xml=reports/negative-tests.xml
    
- name: Run E2E negative tests (Playwright)
  run: |
    npx playwright test e2e/negative/ --reporter=html
```

---

## Maintenance

- Update known expected failures when LLM integration is wired
- Re-verify arithmetic constants if business rules change
- Add new tests when new endpoints are added
- Verify role list if RBAC roles change

**Last Updated:** 2026-08-24  
**Maintainer:** AI Agent (test suite)
