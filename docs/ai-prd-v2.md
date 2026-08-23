# Core Cash — AI Product Requirements Document

**Version**: 2.0
**Date**: 21 August 2026
**Status**: Approved — ready for implementation
**Changes from v1.0**: Reflects all 44 client-confirmed decisions. Updated rules, thresholds, scope changes, and new system behaviours.
**Audience**: Product leadership, engineers making architectural decisions, LangGraph engineer

---

## 1. What Core Cash Is

Core Cash is an **agentic AI treasury decision layer** for corporate CFOs and treasury teams. It is not a Treasury Management System (TMS). It is an intelligence layer that sits above or beside existing systems — banks, ERP, TMS, Excel — and converts cash data into explainable recommendations.

**Core positioning**:
- Reads data from banks, ERP, TMS, Excel, and aggregators
- Validates and normalises that data
- Explains liquidity risk and cash movement
- Recommends the next-best treasury action with mandatory human approval
- Does not move funds. Does not initiate payments. Does not replace existing systems.

---

## 2. What "AI" Means in Core Cash

AI in Core Cash is not a chatbot layered on top of a dashboard. It is an **agentic reasoning system** made up of 8 specialised agents, each responsible for a specific treasury decision domain.

| Agent | Type | Role |
|---|---|---|
| 1 — Daily Cash Position | Deterministic | Consolidated cash visibility |
| 2 — Forecast Intelligence | Deterministic + LLM optional | 7/30/60-day forward projection |
| 3 — Liquidity Risk | Deterministic | Risk scoring and alert generation |
| 4 — Action Recommendation | LLM (Claude 3.5 Sonnet) | Next-best treasury action with Why/What/When/Control |
| 5 — Variance Explanation | Deterministic + LLM | Why actual cash differed from forecast |
| 6 — CFO Summary | LLM (Claude 3.5 Sonnet) | Management-ready narrative report and daily briefing |
| 7 — Treasury Continuity | Deterministic retrieval | Historical precedent lookup for institutional memory |
| 8 — Policy-aware Control | Deterministic rules | Middleware — validates all recommendations before surfacing |

The AI does not read raw files. All data passes through the parser → validation → mapping → normalised cash model pipeline before any agent processes it.

---

## 3. MVP Scope

### In Scope

| Feature | Description |
|---|---|
| Cash visibility | Consolidated position by entity, bank, account, and currency |
| 7/30/60-day forecast | Forward cash projection using AR, AP, recurring flows, and manual assumptions |
| Variance explanation | Why actual cash differed from prior forecast, with named drivers |
| Liquidity risk scoring | 1–10 risk score with threshold breach detection and AR concentration analysis |
| Action recommendations | Up to 10 recommendations per run with Why/What/When/Control structure |
| CFO Summary report | 7-section daily executive report with MTD cash position |
| Daily Briefing | Plain-text ±4-day narrative for CFO leadership conversations |
| File uploads | CSV (primary), BAI2, camt.053, MT940 for bank balances; CSV for AR/AP |
| Account Master | CRUD for accounts with OD limit and min threshold configuration |
| FX Rate admin | Manual daily rate entry by designated admin per entity |
| Investment policy | Admin-uploaded SOP; entity-level cut-off configuration |
| AI Chat panel | Conversational retrieval over existing agent outputs |

### Out of Scope for v1

- Autonomous fund movement or payment initiation
- Direct bank API integrations (file-based only)
- Full TMS replacement
- PDF upload parsing (pending sample file assessment)
- Excel upload support (pending QuickBooks testing)
- Trends & History page (Phase 2 — requires 3–6 months of live data)
- Forecast Confidence metric (Phase 2)
- Multi-user real-time collaboration
- Mobile app
- Advanced scenario modelling
- Production secrets management (use env vars in dev)
- Load testing (post-MVP)
- Real LLM wiring for Agents 4, 5, 6 (mock outputs for Steps 2–8; real Claude API post-Step-8 approval)

---

## 4. Non-Negotiable Product Rules

These rules are enforced across all documentation, agent logic, API responses, and UI. No engineer or designer may deviate from them without explicit product lead sign-off.

### Rule 1: Why / What / When / Control — Mandatory
Every AI recommendation must include all four fields:
- **Why**: The driver or risk behind the recommendation
- **What**: The specific evaluative action proposed
- **When**: The deadline or cut-off time
- **Control**: The approval owner (per DOA policy) and policy check result

No recommendation object may have any of these fields null or empty. Agent 8 (Policy-aware Control) blocks any recommendation that fails this check.

### Rule 2: Read-Only MVP
No UI affordance implies autonomous action. No agent initiates any fund movement, payment, or investment. Every recommendation remains in `Pending` state until a user explicitly approves, rejects, or marks it complete. There is no "auto-approve" mode.

### Rule 3: Predictions ≠ Forecasts — Architecturally Separate
Pattern-based signals (Agent 2, pattern mode) and deterministic forecasts (Agent 2, forecast mode) are:
- Served from different endpoints (`/trends/predictions` vs. `/forecast`)
- Different response shapes
- Different UI components
- Never merged in a single API response

This is a structural product decision, not a styling preference.

### Rule 4: Daily Briefing Stays Prose
The Daily Briefing page renders plain text only. No metric cards, no status badges, no structured data components. It is a prose narrative for CFO leadership conversations. This must not be restructured, regardless of how it might be tempting to surface additional data.

### Rule 5: Human Approval Is Central
Every recommendation component in the UI must surface:
- The approval owner (by name or role, per DOA policy)
- The current approval status (Pending / Approved / Rejected / Completed)
- An explicit confirmation action (Approve / Reject buttons)

No recommendation may show as "completed" without a recorded human approval event.

### Rule 6: Explainability Required
Agents must include rationale in their outputs, not just the conclusion. A risk score without score_breakdown is insufficient. A recommendation without Why is blocked. A variance figure without drivers is incomplete. Explainability is not optional copy — it is a structural requirement.

### Rule 7: Validated Data Only
AI agents never read raw uploaded files. All uploaded data passes through:
1. Parser (format-specific: CSV, BAI2, camt.053, MT940)
2. Validation (required columns, data types, business rules)
3. Column mapping (raw columns → normalised model fields)
4. Normalised cash model (database write)

Only after step 4 do agents consume the data.

### Rule 8: Evaluative Language on Recommendations
The `what` field of every recommendation must use evaluative language:
- Permitted: Evaluate / Consider / Review / Propose / Escalate
- Prohibited: Transfer / Execute / Send / Move / Initiate / Pay

This is enforced by Agent 8 and must be tested.

### Rule 9: No Forced Variance Allocation
Agent 5 (Variance Explanation) must never force variance drivers to sum to zero. If attribution is incomplete, the residual is explicitly reported as **Unexplained Variance** and surfaced to the user for manual investigation. Inventing a driver to close the gap is a product violation.

### Rule 10: OD Limit Never Merged with Usable Cash
Overdraft limit and Usable Cash are always displayed as two separate, distinct figures. A user must never see a combined number that blends cash and OD headroom without explicit labelling. The display is: "$X Usable Cash | OD Limit: $Y available."

---

## 5. Page-by-Page Functional Breakdown

### Page 1: Dashboard
**User outcome**: I can see exactly where my cash is, whether it's at risk, and what I should do about it — in one view.

Key components:
- Cash position header (Total, Available, Restricted, OD Limit, Usable Cash — all five, separately)
- Currency breakdown + Entity breakdown (both — Option C confirmed)
- Account Breakdown Table with Entity column, 70% status threshold, OD display per account
- Liquidity Status Card (Normal / Attention / Critical)
- AI Recommendation Card (max 10; Why/What/When/Control; evaluative language)
- Risk Score (1–10; revised weights; capped at 10)
- AR Concentration Risk panel
- Exceptions & Alerts panel

### Page 2: Forecast
**User outcome**: I can see where my cash will be in 7, 30, and 60 days, understand the assumptions, and adjust them.

Key components:
- Period selector (7/30/60-day tabs) — triggers re-run on selection
- Summary metrics (Opening / Inflows / Outflows / Closing) — Opening Balance logic TBD
- Bar / Line / Waterfall chart views with significant outflow flags (>10% of Usable Cash)
- Entity Forecast Table in entity's base currency, 70% threshold
- Manual Assumptions Editor (UI form entry only — no file upload; confidence as %; 50% threshold)
- Variance Analysis (Total Variance, Variance %, Forecast Accuracy ±5%, Unexplained Variance)

### Page 3: Uploads
**User outcome**: I can get my cash data into the system reliably.

Key components:
- Bank Balance upload zone (CSV, BAI2, camt.053, MT940; PDF pending)
- AR Data upload zone (CSV; PDF pending)
- AP Data upload zone (CSV; PDF pending; triggers forecast re-run)
- **No Manual Assumptions upload zone** — assumptions entered via Forecast page UI
- Column Mapping UI with save-as-template
- Account Master Table with CRUD, OD Limit field, Refresh Frequency field
- FX Rate admin screen (location at design team's discretion)

### Page 4: CFO Summary
**User outcome**: I can share a management-ready cash report today, without manually assembling it.

Key components:
- Live AI Insights panel (1-hour refresh + manual trigger; Cash Runway, Risk Score, Variance %, Forecast Accuracy)
- 7-section exportable report
  - Cover (MTD, not YTD, in summary stats)
  - Executive Summary narrative
  - Cash Position table (Entity | USD Equivalent | **MTD Change** | Trend)
  - Forecast Outlook (7/30/60-day; 70% threshold)
  - Actions Required (Why/What/When/Control; max 10; DOA approval owner)
  - Variance Explanation (Unexplained Variance surfaced)
  - Data Caveats
  - Source References
- Email / PDF / Print export actions

### Page 5: Daily Briefing
**User outcome**: I can walk into a CFO conversation prepared, without needing to interpret multiple systems first.

Key components:
- Behind Us (last 4 days): date + prose narrative + optional Treasury Continuity precedent callout
- Ahead of Us (next 4 days): date + prose narrative + Major Outflow Alert (>10% of Usable Cash)
- If Nothing Changes Outlook: conditional prose statement
- **Plain text only — no cards, no metrics, no structured components**

### Page 6: Trends & History
**Status**: Deferred to Phase 2. Not in MVP.

---

## 6. System Configuration

Core Cash has several configurable parameters, managed by a designated admin per client entity.

| Config | Default | Managed By |
|---|---|---|
| Warning threshold % | 70% | Admin (via system_config table) |
| Forecast confidence threshold | 50% | Admin (via system_config table) |
| Significant outflow threshold | 10% of Usable Cash | Admin (via system_config table) |
| Live Insights refresh interval | 60 minutes | Admin (via system_config table) |
| FX rates (GBP→USD, EUR→USD) | Manual entry daily | Designated FX admin (1 per entity) |
| Investment policy | SOP upload | Admin (latest version always active) |
| Investment cut-off times | Entity-level | Admin (editable) |
| Approval hierarchy | DOA policy reference | Admin (editable) |
| Payroll frequency | Monthly on 25th | Entity setup |
| Tax payment schedule | Quarterly | Entity setup |

---

## 7. Data Model (Normalised Cash Model)

All uploaded data is normalised to this internal model before agents consume it.

**Core tables**:
- `client` — multi-tenant
- `legal_entity` — entity (US HQ, UK Operations, EU Entity, Consolidation)
- `bank` — bank reference
- `account` — with `min_threshold`, `restricted_flag`, `od_limit`, `currency`, `entity_fk`, `refresh_frequency`
- `statement` — `opening_balance`, `closing_balance`, **`available_balance`** (new v2.0), `statement_date`
- `transaction` — `date`, `value_date`, `amount`, `debit_credit`, `description`, `counterparty`
- `source_file` — ingestion audit trail
- `ar_schedule` — expected AR receipts (upload-only)
- `ap_schedule` — expected AP payments (upload-only)
- `manual_assumptions` — with `confidence_pct` (new v2.0; replaces enum)
- `fx_rates` — daily admin-entered FX rates (new v2.0)
- `recommendation_history` — logged decisions for Agent 7
- `investment_policy` — uploaded SOP per entity (new v2.0)
- `entity_investment_cutoffs` — cut-off time per entity (new v2.0)
- `system_config` — configurable thresholds per client (new v2.0)

---

## 8. Integration Architecture

**File ingestion pipeline**:
```
Upload → Parser (CSV/BAI2/camt/MT940) → Validation → Column Mapping → Normalised Model → Agent Layer
```

**Agent execution flow** (sequential, MVP):
```
Daily Cash Position
  ↓
Liquidity Risk     Forecast Intelligence [BLOCKED]
  ↓                         ↓
Action Recommendation (depends on both)
  ↓
Variance Explanation
  ↓
CFO Summary (depends on all above)
  ↓
Treasury Continuity    Policy-aware Control (middleware)
```

**Data delivery to frontend**:
- Cash Position, Liquidity Risk, Recommendations: REST polling on page load
- Live Insights (CFO Summary): REST polling every 60 minutes + manual trigger
- Chat: Server-Sent Events (SSE streaming)
- Forecast: REST polling; re-triggered on AP upload or assumption change

---

## 9. Open Decisions (Must Resolve Before Indicated Build Steps)

| # | Decision | Blocks | Owner |
|---|---|---|---|
| 1 | Opening balance alignment logic (prior-day closing vs. other anchor) | Step 4 — Forecast Agent | Paul + amit j |
| 2 | PDF sample files for parser feasibility assessment | Upload module — PDF parsers | amit j |
| 3 | Investment cut-off time values per entity (USD, GBP) | Step 5 — Action Recommendation | amit j |
| 4 | Investment policy document per entity | Step 5 — investment recs | amit j |
| 5 | QuickBooks file format test (CSV vs. Excel export) | File format decision | amit j |

---

## 10. Success Criteria for MVP

**The product is MVP-ready when**:

1. A treasury user can log in and see a consolidated cash position across all entities, banks, accounts, and currencies — with correct Usable Cash, OD Limit, and Data Confidence.
2. The forecast page shows 7/30/60-day projections with assumptions visible and editable.
3. The system produces at least one recommendation with all four Why/What/When/Control fields populated and correct evaluative language.
4. The CFO Summary report can be generated and exported — with MTD change, actions, variance drivers, and source references.
5. The Daily Briefing renders as prose, includes a Major Outflow Alert where applicable, and surfaces a Treasury Continuity precedent callout where relevant history exists.
6. The Variance Explanation surfaces Unexplained Variance when drivers do not fully account for the total — never forcing the residual to zero.
7. Risk score calculation is correct (70% threshold, revised weights, capped at 10).
8. All agent outputs are traceable by `run_id`.
9. All recommendations require and record human approval — no autonomous action.
10. Frontend mock data and backend real API responses are byte-for-byte identical (schema contract matched).

---

## 11. Chatbot Scope (MVP)

The AI Chat panel is a **conversational retrieval layer** over existing agent outputs — not a new reasoning engine.

**Confirmed scope for MVP**:
- Balance and position questions → retrieves Agent 1 output
- Risk and shortfall questions → retrieves Agent 3 + Agent 2 outputs
- Recommendation explanations → retrieves Agent 4 output
- Daily summary → retrieves Agent 6 output

**Out of scope for MVP**:
- Ad-hoc analysis beyond existing agent outputs
- Natural language queries over raw transaction data
- Writing or editing assumptions via chat
- Approving recommendations via chat

**Architecture**: Chat handler queries the latest agent outputs from the normalised model. It does not invoke a new agent run. It composes a natural language response from cached agent data.

---

## Change Log: v1.0 → v2.0

| Area | Change |
|---|---|
| Global threshold | 80% → 70% warning threshold everywhere |
| Naming | "Concentration Risk" → "AR Concentration Risk" everywhere |
| Variance | No forced allocation; Unexplained Variance surfaced explicitly |
| AP/AR | Confirmed upload-only; no manual edits |
| Time zone | EST as system default |
| Trends page | Deferred to Phase 2 |
| One-off detection | Two rules: 10% of Usable Cash (operational) + 3× avg (statistical) |
| FX rates | Database table; admin entry; prior-day fallback |
| Cash definitions | Five distinct terms defined and locked |
| OD Limit | New field; separate display; never merged with Usable Cash |
| Data Confidence | Two-step bank feed rule; 7-day threshold for manual feeds |
| Schema | `available_balance` on Statement; `od_limit` on Account |
| Forecast shortfall | Uses projected closing usable cash (not opening balance) |
| Dashboard | Currency + entity breakdown both displayed |
| Account table | Entity column added |
| Recommendations | Evaluative language enforced; investment recs added; DOA approval; 10-item cap |
| Risk score | +2 breach (was +3); +2 shortfall (was +1); capped at 10 |
| Forecast | Assumptions: UI entry only; 50% confidence threshold; net-new items only |
| Variance metrics | Variance % added; ±5% tolerance; Unexplained Variance |
| File formats | CSV + structured; PDF pending sample; assumptions = UI entry |
| Live Insights | 1-hour refresh (was 60 seconds) |
| Cash Runway | Blended 50/50 historical + forecast; one-offs excluded |
| CFO Summary | MTD replaces YTD |
| Daily Briefing | Major Outflow Alert at 10% of Usable Cash |
| Chatbot | Retrieval-over-agents confirmed; no new reasoning capability |
| New tables | `fx_rates`, `investment_policy`, `entity_investment_cutoffs`, `system_config`, `recommendation_history` |
