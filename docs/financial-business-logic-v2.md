# Core Cash — Financial Business Logic & Calculations

**Version**: 2.0
**Date**: 21 August 2026
**Status**: Approved — ready for backend implementation
**Changes from v1.0**: All 44 decisions from client review cycle incorporated. See change log at end of document.
**Audience**: Backend engineers, LangGraph engineer, product lead

---

## Overview

This document specifies the financial logic, calculations, and business rules for every metric, card, table, and section in Core Cash. Each page is broken down section-by-section with:
- **What is displayed**
- **How it is calculated**
- **Data sources**
- **Assumptions**
- **Edge cases**

---

## GLOBAL RULES (Apply Across All Pages)

### Status Threshold (Global)
```
Green  : balance >= min_threshold
Yellow : balance >= min_threshold × 0.70
Red    : balance < min_threshold × 0.70
```
Applies everywhere status colour is derived from balance vs. minimum threshold. No exceptions.

### AR Concentration Risk
Label: **AR Concentration Risk** everywhere. Metric = top 3 counterparties as % of total AR outstanding. Not applied to cash or AP.

### Unexplained Variance
Variance drivers explain as much as data supports. Any remainder is explicitly reported as **Unexplained Variance**. No forced allocation to zero under any circumstances.

### AP and AR Data
Both are upload-only. No manual creation or editing of AP/AR line items. A new file upload replaces the prior dataset entirely.

### Manual Assumptions
Manual assumptions are exclusively net-new cash flow items not present in any AR or AP schedule. No override of or linkage to AR/AP line items. The double-count concern is structurally resolved by this separation.

### Default Time Zone
All scheduling and cut-offs default to **US EST**. UK (GMT) and EU (CET) are configurable overrides.

### One-Off Transaction Detection
Two rules coexist with different purposes:
- **Rule A — Operational alert** (Forecast, Daily Briefing): Any single-day outflow exceeding **10% of Usable Cash** is flagged as a significant outflow.
- **Rule B — Statistical detection** (Variance Explanation): Any outflow exceeding **3× the 30-day average daily outflow** is classified as a one-off for variance driver attribution.

---

## PAGE 1: DASHBOARD

### Section 1.1: FX Rate Configuration

| Parameter | Rule |
|---|---|
| Storage | `fx_rates` database table — not a config file |
| Refresh | Daily at 09:00 UTC by designated admin |
| Rate type | Mid-market; no bid/ask spread modelling |
| Admin access | 1 designated user per client entity |
| Missing rate | Warning banner displayed; prior day's rate used; calculations not blocked |
| Consistency | Same rate applies across Dashboard, Forecast, Variance, CFO Summary, Reports |

**UI requirement**: FX Rate admin screen with one entry field per currency (GBP→USD, EUR→USD), last-updated timestamp, and audit log.

---

### Section 1.1: Cash Position Definitions

| Term | Definition | Data Source |
|---|---|---|
| **Total Cash** | Sum of `closing_balance` across all accounts, converted to USD | `Statement.closing_balance` × FX rate |
| **Available Cash** | Bank-reported available balance after uncleared/pending items | `Statement.available_balance` — separate stored field |
| **Restricted Cash** | Sum of balances on accounts where `restricted_flag = true`; minimum threshold reserves only; dynamic bank restrictions excluded from MVP | `Account.restricted_flag` |
| **OD Limit** | Configured overdraft facility per account; displayed separately; never merged into cash totals | `Account.od_limit` (nullable) |
| **Usable Cash** | Available Cash − Restricted Cash | Derived |

**Display rule**: Usable Cash and OD Limit are always two separate figures. Never merge them. Example display: "$8.2M Usable Cash | OD Limit: $2.0M available."

**Negative closing balance**: Valid — indicates OD utilisation. Not an error. System flags the account as OD-utilised and shows consumed vs. remaining OD headroom.

**Schema changes (v2.0)**:
- `Statement` table: add `available_balance` (numeric, nullable)
- `Account` table: add `od_limit` (numeric, nullable)

---

### Section 1.1: Data Confidence

**Bank feed confidence**:
```
All feeds refreshed within 24h, no feeds missing   → High
Any feed 24–48h stale OR one feed missing          → Medium
Any feed >48h stale OR multiple feeds missing      → Low
```

**Manual feed confidence**:
```
Manual feed up to 7 days old                       → High
Manual feed older than 7 days                      → Low (warning flag displayed)
```

**Feed missing detection**: Driven by `Refresh_Frequency` field on Account Master:
- `Daily` accounts with no ingestion record for today = missing feed
- `Weekly` accounts expected once per 7 days
- `Manual` accounts never flagged as missing

This dependency must be implemented before confidence logic can evaluate bank feed status.

---

### Section 1.2: Liquidity Status Card

**Liquidity Status logic**:
```
if any account has current_balance < min_threshold      → Critical
if any 7-day forecast day has projected closing
  usable cash < min_threshold for any entity            → Attention (Forecast Shortfall)
if AR Concentration Risk > 70%                          → Attention
if any bank feed stale >48h                             → Attention
else                                                    → Normal
```

**Forecast Shortfall definition**:
```
Projected Closing Usable Cash (Day D) =
  Closing Balance (Day D-1) + Expected Inflows (Day D) − Expected Outflows (Day D)

Shortfall = any day in 7-day forward forecast where:
  Projected Closing Usable Cash < min_threshold (account or entity level)
```

Tracked at both account level and entity level.

---

### Section 1.3: Top Metrics Row

| Metric | Calculation |
|---|---|
| **Usable Cash** | Available Cash − Restricted Cash (see 1.1) |
| **Total Restricted** | Sum of all account balances where `restricted_flag = true`, USD equivalent |
| **Data Confidence** | Overall level: lowest of any individual feed (see 1.1) |
| **7-Day Forecast** | Forecast Intelligence Agent output, `closing_cash` field, horizon = 7 days |

**Total Restricted display**: Aggregate figure in dashboard header. Per-account / per-entity breakdown visible in Account Breakdown Table (Section 1.5).

---

### Section 1.4: Cash by Currency and by Entity

Two views displayed (as sub-sections or toggle):

**View A — By Currency**:
```
For each currency C:
  Amount (C)       = Sum of available_balance where account.currency = C
  Amount (USD Eq.) = Amount (C) × FX_rate(C)
  Share (%)        = Amount (USD Eq.) / Total Available Cash × 100
```
Show only currencies with non-zero balance. Order by amount descending.

**View B — By Entity (USD)**:
```
For each legal entity E:
  Entity Cash (USD Eq.) = Sum of available_balance for all accounts in E, × FX_rate
```
Order by amount descending.

---

### Section 1.5: Account Breakdown Table

Column order (left to right):

| Entity | Account Name | Bank | Currency | Current Balance | Min Threshold | Status | Confidence |

- **Entity**: `LegalEntity.name`
- **Current Balance**: `Statement.available_balance` (latest per account)
- **Min Threshold**: `Account.min_threshold` in local currency
- **Status**: Green / Yellow / Red per global threshold rule (70%)
- **Confidence**: Per feed staleness rule (Section 1.1)

Accounts grouped by Entity (collapsible). Entity row shows entity total in USD equivalent.

**Entity total**:
```
Entity Total (USD Eq.) = Sum of available_balance for all accounts in entity × FX_rate
```

---

### Section 1.6: AI Recommendation Card

**Structure**: Why / What / When / Control (all four fields mandatory on every recommendation).

**Language rule**: Evaluative only. Permitted: Evaluate / Consider / Review / Propose / Escalate. Prohibited: Transfer / Execute / Send / Move / Initiate.

**Required fields**:
- **Why**: Driver context (e.g., "EUR balance €70K below €500K minimum; €120K AP due Friday")
- **What**: Specific evaluative action (e.g., "Evaluate EUR 200K funding for EU Entity from BofA EUR Reserve, subject to approval")
- **When**: Deadline + investment cut-off time at entity level (e.g., "Today, before 14:00 EST — entity investment cut-off")
- **Control**: DOA-based approval owner + policy check result (e.g., "Finance Director per DOA policy; restricted account check: pass")

**Investment recommendations**:
- Triggered when surplus cash is projected for 7+ consecutive days above min_threshold
- Requires an investment SOP/policy uploaded by admin; without it, system flags surplus only — no vehicle recommendation
- Investment cut-off time is configured at entity level (not per currency or bank)
- One designated investment account per entity, irrespective of currency

**Approval hierarchy**: Based on company's DOA policy, editable by admin on an ongoing basis.

**Output cap**: Maximum 10 recommendation items per run.

**Approval workflow**: Every recommendation surfaces approval owner and requires explicit human confirmation before any "action taken" state is recorded. No autonomous execution.

---

### Section 1.7: Liquidity Risk Section

**Risk Score**:
```
Base Score  = 1
Breach      = +2 per active breach of min_threshold (capped at 6)
Stale feed  = +1 if any bank feed > 48h stale
AR conc.    = +1 if top 3 counterparties > 70% of total AR outstanding
Shortfall   = +2 if any day in 7-day forecast has projected usable cash < min_threshold
Raw total   = capped at 10 (truncate if raw exceeds 10)
```

Scale: 1–3 = Low (green); 4–6 = Medium (yellow); 7–10 = High (red).

**Active Breaches List**:
Column order: **Entity | Account Name | Min Threshold | Current Balance | Shortfall | Currency**
```
Breach = current_balance < min_threshold
Shortfall amount = min_threshold − current_balance
```

**AR Concentration Risk**:
```
Total AR Outstanding     = Sum of all expected AR receipts (AR Schedule)
Top 3 AR by counterparty = Sum of expected AR for 3 largest counterparties
Concentration (%)        = Top 3 / Total AR × 100
```
Risk threshold: >70% = flag. Label: "AR Concentration Risk."

---

### Section 1.8: Exceptions & Alerts Panel

| Alert Type | Trigger | Urgency |
|---|---|---|
| Threshold Breach | `current_balance < min_threshold` | Critical |
| Forecast Shortfall | Projected closing usable cash < min_threshold in 7-day window | High |
| Stale Bank Feed | No ingestion >48h on a Daily-frequency account | Warning |
| AR Concentration Risk | Top 3 counterparties > 70% of total AR | Medium |
| Unmapped Account | Uploaded account number not in Account Master | Warning |

Display order: Critical → High → Medium → Warning.

---

## PAGE 2: FORECAST

### Section 2.1: Period Selector (7 / 30 / 60 Day Tabs)

Selecting a tab triggers the Forecast Intelligence Agent for that horizon. All downstream sections update.

Forecast re-runs are also triggered manually when:
- User updates a manual assumption (edit, add, delete)
- User uploads a new AP file

Forecasts do not auto-react to AR data changes.

**Forecast Confidence**: Not in MVP scope. Deferred to Phase 2.

---

### Section 2.2: Summary Metrics (Opening / Inflows / Outflows / Closing)

**Opening Cash**:
```
Opening Cash = prior-day closing balance from most recently ingested bank statement
```
⚠️ **Opening balance alignment logic is OPEN** — do not implement Step 4 (Forecast Intelligence Agent) until resolved. See backend-build-handoff.md.

**Expected Inflows**:
```
Sum of:
  - AR receipts expected within horizon (from AR Schedule, upload-only)
  - Loan drawdowns / intercompany receipts
  - Investment redemptions and maturity proceeds
  - Manual assumptions: Inflow direction, confidence ≥ 50%
```
Note: New investment placements are Outflows. Investment redemptions/proceeds are Inflows.

**Expected Outflows**:
```
Sum of:
  - AP payments expected within horizon (from AP Schedule, upload-only)
  - Payroll (manual assumption or recurring schedule)
  - Taxes (manual assumption or schedule)
  - Bank fees (manual assumption)
  - New investment placements
  - Loan repayments
  - Capex payments
  - Manual assumptions: Outflow direction, confidence ≥ 50%
```

**Forecast Closing**:
```
Forecast Closing = Opening Cash + Expected Inflows − Expected Outflows
```

---

### Section 2.3: Chart Views

**Bar Chart (Daily Closing Balance)**:
```
For each day D in [start_date, end_date]:
  Daily Closing (D) = Closing (D-1) + Inflows (D) − Outflows (D)
```
- Red threshold line at min_threshold
- Green shaded zone: above threshold
- Red shaded zone: below threshold

**Line Chart**: Same data as bar chart, rendered as trend line with historical actuals as dashed overlay where available.

**Waterfall Chart**: Opening → +Inflows → −Outflows → Closing. Each segment labelled in USD equivalent.

**Significant outflow flag on chart**: Any single day where outflow > 10% of Usable Cash is flagged with a marker on the chart.

---

### Section 2.4: Entity Forecast Table

Column order:

| Entity Name | Opening | Expected Inflows | Expected Outflows | Forecast Closing | Status |

- All values in **entity's base currency** (not USD)
- Consolidated total row at bottom in USD equivalent
- Status uses 70% threshold against min_threshold in entity's base currency
- Default sort: descending by Opening balance; sortable by any column

---

### Section 2.5: Manual Assumptions Editor

**Entry method**: UI form only. No CSV or file upload for assumptions. The Assumptions upload zone is removed from the Uploads page.

**Assumption fields**:

| Field | Type | Required | Notes |
|---|---|---|---|
| Entity | Dropdown | Yes | Which entity this flow impacts |
| Currency | Dropdown | Yes | Local currency |
| Direction | Inflow / Outflow | Yes | Direction of cash flow |
| Amount | Number | Yes | Amount in local currency; > 0 |
| Date | Date | Yes | When this flow occurs; ≥ today |
| Category | Dropdown | Yes | Payroll / Tax / Investment / Loan Repayment / Capex / Operating / Other |
| Description | Text | Yes | Free-text explanation |
| Confidence (%) | Number 0–100 | Yes | User's assessed probability |

**Confidence threshold**:
```
Confidence ≥ 50%  → Included in forecast (label: "Included")
Confidence < 50%  → Excluded from forecast (label: "Excluded from forecast — confidence below threshold")
```
Default threshold = 50%. Stored in system config; adjustable by admin without code change.

**Scope**: Net-new items only. Manual assumptions cannot reference or override AR or AP line items. AP and AR are upload-only and immutable between uploads.

**Multiple assumptions on same date**: All included assumptions are summed for that day.

**Assumptions are applied globally**: Once created, active until deleted or expired.

**Edit behaviour**: New value replaces old value in forecast immediately. Prior value retained in audit log (timestamped, user-attributed) but not used in calculations.

**Audit**: Every create / update / delete logged with user identity and timestamp.

---

### Section 2.6: Variance Analysis

**Variance Metrics**:

| Metric | Definition | Calculation |
|---|---|---|
| **Total Variance** | Actual closing (day N) vs. forecast closing (run on day N-1) | Actual(N) − Forecast(N) |
| **Variance Direction** | Favorable or Unfavorable | If Total > 0: Favorable; else Unfavorable |
| **Variance %** | Percentage deviation of actual from forecast | (Actual − Forecast) / \|Forecast\| × 100 |
| **Forecast Accuracy (%)** | % of daily forecast points within ±5% of actual | Count(days where \|Actual−Forecast\| < Forecast×0.05) / Total days × 100 |

**Top Drivers Breakdown**:
Decomposition of total variance into named causes. Drivers explain as much variance as data supports. Any residual is reported explicitly as **Unexplained Variance** — never forced to zero.

One-off detection for variance (Rule B): Any outflow exceeding 3× the 30-day average is classified as a one-off driver in the variance breakdown.

---

## PAGE 3: UPLOADS

### Section 3.1: Supported File Formats

| Upload Type | Formats Supported | Build Order |
|---|---|---|
| Bank Balances | CSV, BAI2, camt.053, MT940, PDF* | CSV + structured formats first; PDF after sample file review |
| AR Data | CSV, PDF* | CSV first; PDF after sample file review |
| AP Data | CSV, PDF* | CSV first; PDF after sample file review |
| Manual Assumptions | **UI entry only — no file upload** | N/A |

*PDF parsers built only after sample files provided by client and assessed by engineering. PDF must be bank-generated / structured format. Ad-hoc/OCR PDFs are out of scope.

Excel (`.xlsx`): Not in initial build scope. To be assessed after QuickBooks sample file testing.

---

### Section 3.1: Validation Rules — Bank Balance Files

**CSV required columns**:

| Column | Required | Validation |
|---|---|---|
| Entity Name | Yes | Must match LegalEntity in system |
| Account Number | Yes | Resolved against Account Master; unmatched → Low Confidence + flag |
| Bank | Yes | Bank name string |
| Currency | Yes | ISO 4217: USD, GBP, EUR |
| Closing Balance | Yes | Numeric; negative permitted (OD utilisation) |
| Statement Date | Yes | Date ≤ today |

**Unmapped accounts**: Accepted; assigned to "Unmapped Accounts" holding category; flagged as Low Confidence; surfaced for human mapping in Account Master. Not rejected.

**Negative Closing Balance**: Valid. System flags account as OD-utilised. If `od_limit` is configured, shows consumed vs. remaining OD headroom.

---

### Section 3.1: Validation Rules — AR Data Files

**CSV required columns**:

| Column | Required | Validation |
|---|---|---|
| Entity Name | Yes | Must match LegalEntity |
| Counterparty | Yes | Customer name |
| Currency | Yes | ISO 4217 |
| Invoice Amount | Yes | > 0 |
| Invoice Date | Yes | Valid date |
| Due Date | Yes | Valid date |
| Aging Days | Yes | Integer ≥ 0; 0 if not yet due |

---

### Section 3.1: Validation Rules — AP Data Files

**CSV required columns**:

| Column | Required | Validation |
|---|---|---|
| Entity Name | Yes | Must match LegalEntity |
| Vendor | Yes | Supplier name |
| Currency | Yes | ISO 4217 |
| Invoice Amount | Yes | > 0 |
| Due Date | Yes | Valid date |
| Status | Yes | Pending / Approved / Disputed |

---

### Section 3.2: Column Mapping UI

Maps raw file columns to Core Cash system fields. Mandatory fields must be mapped before file is accepted. Optional fields can be left unmapped. "Save as template" option for re-use.

Indicator: "X of Y mandatory fields mapped."

---

### Section 3.3: Account Master Table

| Column | Type | Editable | Notes |
|---|---|---|---|
| Account Number | Text | No | Unique identifier |
| Account Name | Text | Yes | Display name |
| Bank | Dropdown | Yes | Bank name |
| Entity | Dropdown | Yes | Owning legal entity |
| Currency | Dropdown | Yes | USD / GBP / EUR |
| Restricted Flag | Checkbox | Yes | Marks account as restricted cash |
| Min Threshold | Number | Yes | Minimum balance in local currency; ≥ 0 |
| OD Limit | Number | Yes | Overdraft facility in local currency; nullable (blank = no OD) |
| Refresh Frequency | Dropdown | Yes | Daily / Weekly / Manual |
| Status | Dropdown | Yes | Active / Inactive / Suspended |
| Include in Cash Position | Checkbox | Yes | Include in consolidated cash |

**Add Account validation**: Account Number unique; Min Threshold ≥ 0; OD Limit ≥ 0 if set; Currency supported; Entity exists in LegalEntity table.

---

## PAGE 4: CFO SUMMARY

### Section 4.1: Live AI Insights Panel

**Refresh**: Scheduled every **1 hour**. Manual "Refresh Now" button available.

**Metrics**:

| Metric | Definition | Calculation |
|---|---|---|
| **Cash Runway (Days)** | Days Usable Cash can sustain current burn | Usable Cash / Blended Average Daily Outflow |
| **Liquidity Risk Score** | 1–10 scale | Liquidity Risk Agent output |
| **Variance %** | Latest period actual vs. forecast | Variance Explanation Agent output |
| **Forecast Accuracy (%)** | % of days within ±5% | Variance Explanation Agent output |

**Cash Runway calculation**:
```
Blended Average Daily Outflow =
  (Sum of actual daily outflows, last 30 days [from bank statements]
  + Sum of projected daily outflows, next 30 days [from forecast]) / 2 / 30

One-off exclusion: Any single-day outflow > 10% of Usable Cash is excluded from
the historical 30-day average. Noted inline: "Excludes [date] one-off outflow of $X."
```
50/50 blending confirmed. Weighting is configurable for future adjustment.

**Trend Chart**: Last 7 days of Cash Runway or Risk Score snapshots. End-of-day snapshot per day.

---

### Section 4.2: Report Cover

- Report Title: "Daily Cash Report – [Date]"
- Forecast Version: version tag of the current forecast model run
- Overall Confidence: lowest confidence level of any input agent
- Summary Stats: Total Cash, Usable Cash, OD Limit, 7-Day Forecast Closing, Status

---

### Section 4.3: Executive Summary (Section 1 of Report)

1-paragraph narrative from CFO Summary Agent: current position, status, key decision(s) needed, confidence level and any data caveats.

---

### Section 4.4: Cash Position (Section 2 of Report)

| Entity | USD Equivalent | MTD Change | Trend |
|---|---|---|---|

- **MTD Change**: Current balance − balance on 1st of current month (USD equivalent)
- **Trend**: Up / Flat / Down based on MTD direction
- One row per entity + consolidated total row

---

### Section 4.5: Forecast Outlook (Section 3 of Report)

| Horizon | Opening | Expected Inflows | Expected Outflows | Forecast Closing | Risk |
|---|---|---|---|---|---|

Three rows: 7 Day, 30 Day, 60 Day.
Risk = Green if Closing ≥ min_threshold; Yellow if ≥ 70% of min_threshold; Red if < 70%.

---

### Section 4.6: Actions Required (Section 4 of Report)

Structured list of active recommendations (Why / What / When / Control).
Approval Status column: Pending / Approved / Rejected / Completed.
Maximum 10 items displayed.

---

### Section 4.7: Variance Explanation (Section 5 of Report)

Narrative from Variance Explanation Agent. Unexplained Variance surfaced explicitly if drivers do not fully account for total variance.

---

### Section 4.8: Data Caveats (Section 6 of Report)

Plain-text list of data quality issues: stale feeds, estimated values, assumptions not yet confirmed.

---

### Section 4.9: Source References (Section 7 of Report)

| Source | File Name | Timestamp | Status |
|---|---|---|---|

Every number in the report traceable to a source in this table.

---

## PAGE 5: DAILY BRIEFING

### Section 5.1: Behind Us (Last 4 Days)

One entry per day: date label + 1–2 sentence narrative of cash events. Optional precedent callout from Treasury Continuity Agent: "Last time this happened [date], the team [action taken] — resolved in [timeframe]."

Data source: CFO Summary Agent (Briefing mode) + Treasury Continuity Agent.

---

### Section 5.2: Ahead of Us (Next 4 Days)

One entry per day: date label + narrative of expected cash events.

**Major Outflow Alert**: If any single expected outflow on a forecast day exceeds **10% of Usable Cash**, a structured alert is surfaced within that day's entry:
- Outflow category (Loan Repayment / Tax / Capex / Large AP)
- Amount and currency
- Entity
- Action required with investment cut-off time if applicable

Categories must be tagged in Manual Assumptions editor (Category field) or AP upload for the system to label them correctly.

---

### Section 5.3: If Nothing Changes Outlook

Conditional statement on cash position if no actions are taken. Data source: CFO Summary Agent (Briefing mode).

---

## PAGE 6: TRENDS & HISTORY

**Status: DEFERRED — Phase 2**

All 9 sections (YoY comparison, self-benchmarking, 6-month chart, surprise ledger, creep detector, counterparty concentration, pattern signals, scenario stress lines, cost-of-cash) are out of MVP scope.

Rationale: requires 3–6 months of live data to be meaningful. Building before data exists produces a hollow feature.

---

## Financial Assumptions & Constants

### FX Rates

```
Default (updated daily at 09:00 UTC by admin):
  1 GBP = [admin-entered rate] USD
  1 EUR = [admin-entered rate] USD

Fallback: Prior day's rate if today's rate not entered; warning banner displayed.
Rate type: Mid-market. No bid/ask spread modelling in MVP.
```

### Thresholds & Policy Defaults

| Policy | Value | Source |
|---|---|---|
| Warning threshold (global) | 70% of min_threshold | Client confirmed |
| Stale bank feed → Medium | >24h and ≤48h | Client confirmed |
| Stale bank feed → Low | >48h | Client confirmed |
| Manual feed → Low | >7 days | Client confirmed |
| AR Concentration Risk threshold | Top 3 > 70% of total AR | Client confirmed |
| High single-counterparty flag | Any single counterparty > 40% of AR | Client confirmed |
| Forecast Accuracy tolerance | ±5% | Client confirmed |
| Confidence threshold for assumption inclusion | ≥50% (configurable) | Client confirmed |
| Significant outflow alert | >10% of Usable Cash | Client confirmed |
| One-off statistical threshold | >3× 30-day average daily outflow | Client confirmed |
| Live Insights refresh | Every 60 minutes + manual trigger | Client confirmed |
| Recommendations cap | 10 items per run | Client confirmed |

### Time Zones & Cut-offs

| Region | Bank Cut-off | Treasury Cut-off | Default |
|---|---|---|---|
| **US (EST)** | 17:00 EST | 16:00 EST | Yes — system default |
| **UK (GMT)** | 15:30 GMT | 14:30 GMT | Configurable |
| **EU (CET)** | 15:00 CET | 14:00 CET | Configurable |

Investment cut-off times are configured at **entity level** (not per currency or bank). One designated investment account per entity irrespective of currency.

### Forecast Assumptions

| Assumption | Default | Override |
|---|---|---|
| AR Collection Rate | 100% on due date | Manual assumption (net-new items only; confidence ≥50%) |
| AP Payment Rate | 100% on due date | New AP file upload |
| Payroll Frequency | Monthly on 25th (configurable per entity) | Entity setup |
| Tax Payment Schedule | Quarterly (Apr 15, Jul 15, Oct 15, Jan 15) | Entity setup |
| FX Movement | Static (admin-entered daily rate) | No volatility modelling in MVP |
| Assumption confidence threshold | 50% | Admin-configurable |

---

## Audit & Validation Rules

1. Every number in the UI is traceable to its source (agent output, calculation, or database query)
2. All monetary amounts are in USD equivalent unless explicitly labelled otherwise
3. All dates/times are UTC unless time zone is explicitly stated
4. Confidence levels are deterministic based on feed freshness — not probabilistic
5. Variance drivers explain as much variance as data supports; residual reported as Unexplained Variance
6. Every recommendation has all 4 components (Why / What / When / Control) — no exceptions
7. AI never reads raw files; data must pass through parser → validation → mapping → normalized model before agent generates output
8. All manual assumption edits are audit-logged with user identity and timestamp

---

## Data Flow Summary

| Agent | Feeds Into |
|---|---|
| Daily Cash Position Agent | Dashboard, CFO Summary report, Live Insights |
| Liquidity Risk Agent | Dashboard, CFO Summary |
| Forecast Intelligence Agent | Forecast page, Dashboard (7-day teaser), CFO Summary |
| Action Recommendation Agent | Dashboard, CFO Summary Actions Required, Daily Briefing |
| Variance Explanation Agent | Forecast variance section, CFO Summary |
| CFO Summary Agent | CFO Summary report, Daily Briefing narrative |
| Treasury Continuity Agent | Daily Briefing (precedent callouts) |
| Policy-aware Control Agent | Middleware — validates all recommendations before surfacing |

---

## Change Log: v1.0 → v2.0

| # | Change | Section |
|---|---|---|
| 1 | Warning threshold changed from 80% to 70% globally | Global |
| 2 | AR Concentration Risk — explicit naming everywhere | Global |
| 3 | Unexplained Variance — no forced allocation | Global |
| 4 | AP and AR confirmed upload-only; no manual edits | Global |
| 5 | Default time zone: EST | Global |
| 6 | Trends & History: Phase 2 | Global |
| 7 | One-off transaction: 10% (operational) + 3× avg (statistical) | Global |
| 8 | FX rates: database table, 09:00 UTC, 1 admin per entity, prior-day fallback | 1.1 |
| 9 | Cash Position definitions clarified and locked (5 distinct terms) | 1.1 |
| 10 | OD Limit added as separate display field; never merged with Usable Cash | 1.1 |
| 11 | Negative closing balance = valid OD utilisation | 1.1 |
| 12 | Data Confidence — two-step bank feed rule confirmed | 1.1 |
| 13 | Manual feed confidence: High ≤7 days; Low >7 days | 1.1 |
| 14 | Feed missing detection via Refresh_Frequency on Account Master | 1.1 |
| 15 | Schema: `available_balance` on Statement; `od_limit` on Account | 1.1 |
| 16 | Forecast shortfall uses projected closing usable cash (not opening balance) | 1.2 |
| 17 | Currency + Entity both displayed on Dashboard (Option C) | 1.4 |
| 18 | Entity column added to Account Breakdown Table | 1.5 |
| 19 | Recommendation language: evaluative only | 1.6 |
| 20 | Investment recommendations: SOP required; entity-level cut-off; DOA approval; 10-item cap | 1.6 |
| 21 | Risk score revised: +2 breach (cap 6), +2 shortfall; capped at 10 | 1.7 |
| 22 | Active Breaches column order updated | 1.7 |
| 23 | Forecast Confidence deferred | 2.1 |
| 24 | Inflows/Outflows: investment and loan classification clarified | 2.2 |
| 25 | Entity Forecast Table: entity's base currency | 2.4 |
| 26 | Manual assumptions: UI entry only; no file upload | 2.5 |
| 27 | Confidence threshold: 50% (was no explicit threshold) | 2.5 |
| 28 | Manual assumptions: net-new only; no AR/AP override | 2.5 |
| 29 | Variance metrics: Variance % added; tolerance ±5%; Unexplained Variance | 2.6 |
| 30 | File formats: CSV + structured formats + PDF (post sample review) | 3.1 |
| 31 | Manual Assumptions upload zone removed from Uploads page | 3.1 |
| 32 | OD Limit field added to Account Master | 3.3 |
| 33 | Live Insights: 1-hour refresh + manual trigger (was 60 seconds) | 4.1 |
| 34 | Cash Runway: 50/50 blended; one-offs excluded | 4.1 |
| 35 | CFO Summary: MTD replaces YTD | 4.4 |
| 36 | Daily Briefing: Major Outflow Alert at 10% of Usable Cash | 5.2 |
