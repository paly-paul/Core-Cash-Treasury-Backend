# Core Cash: Backend Product Requirements Document

**Version:** 2.1
**Date:** August 22, 2026
**Audience:** Product Managers, Backend Engineers, Architects, QA Engineers
**Status:** Ready for Development

---

## What Changed in v2.1

| Area | v2.0 | v2.1 | Rationale |
|---|---|---|---|
| **F2 File Formats** | Listed Excel as supported | Excel removed from MVP scope | C7 resolution: Excel parser adds complexity without proportional value; CSV covers the same structured data use case |
| **Out of Scope** | Excel not explicitly called out | Excel file parser added to Out of Scope | Clarity for engineering team |
| **F4 Threshold language** | "Approaching minimum" (vague) | "Yellow status at ≥70% of min_threshold utilisation" | Aligns with confirmed business rule: 70% warning threshold, not 80% |
| **document version** | 2.0 | 2.1 | Targeted corrections; no architectural changes |

---

## What Changed in v2.0

This document supersedes v1.0 (July 28, 2026). The underlying technology stack has shifted. All product requirements, acceptance criteria, and business rules are unchanged. Only the technology implementation changes.

| Area | v1.0 | v2.0 | Impact on Requirements |
|---|---|---|---|
| **App backend language** | ASP.NET Core (.NET 8) | Python / FastAPI | No functional change; same endpoints, same behavior |
| **Schema contract layer** | Manual sync (language boundary) | Shared Pydantic lib | Stronger type safety; fewer integration bugs |
| **Job queue** | ElastiCache Redis | AWS SQS | No functional change; same async pattern |
| **AI output store** | PostgreSQL (same DB) | MongoDB | No functional change; polling endpoints same |
| **Chat protocol** | REST polling | SSE (streaming) | Chat panel now streams tokens; better UX |
| **Inter-service comms** | HTTP REST (direct calls) | SQS (async only) | No functional change; AI backend fully decoupled |

**What did NOT change:**
- All 10 functional requirements (F1–F10)
- Every API endpoint, request/response shape
- Why/What/When/Control mandate on every recommendation
- Read-only MVP posture (no autonomous fund movement)
- 8-agent architecture
- Security, compliance, audit requirements
- Performance targets
- Success metrics

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Product Overview](#product-overview)
3. [Strategic Positioning](#strategic-positioning)
4. [Scope & Constraints](#scope--constraints)
5. [Backend Subsystems](#backend-subsystems)
6. [Functional Requirements](#functional-requirements)
7. [Non-Functional Requirements](#non-functional-requirements)
8. [API Specifications](#api-specifications)
9. [Data Model & Storage](#data-model--storage)
10. [Security & Compliance](#security--compliance)
11. [Performance & Scalability](#performance--scalability)
12. [Error Handling & Resilience](#error-handling--resilience)
13. [Integration Points](#integration-points)
14. [Testing Strategy](#testing-strategy)
15. [Success Metrics](#success-metrics)
16. [Out of Scope](#out-of-scope)
17. [Glossary](#glossary)

---

## Executive Summary

**Core Cash** is an **agentic AI treasury decision layer** for enterprise customers in the US financial and banking sector. The backend delivers:

- **Explainable AI recommendations** answering Why/What/When/Control for every treasury action
- **Multi-source cash visibility** aggregating data from banks, ERPs, and TMSs
- **Liquidity forecasting** for 7/30/60-day horizons with variance explanation
- **Audit-grade security** with encryption, role-based access, and compliance logging
- **Enterprise reliability** via Multi-AZ databases, auto-scaling, and durable job processing

**Architecture (v2.0):**
- **App Backend:** Python / FastAPI — treasury platform layer (file ingestion, cash data, approvals, job publishing)
- **AI Backend:** Python / FastAPI + LangGraph — 8 agents, Claude 3.5 Sonnet LLM calls, job consumption, result writing
- **Shared Python Library:** Pydantic schemas and types shared across both services (single source of truth)
- **AWS SQS:** Async job queue decoupling app backend from AI backend
- **PostgreSQL:** Relational store for treasury data (owned by app backend; read-only to AI backend)
- **MongoDB:** Document store for agent outputs, recommendations, audit history (owned by AI backend)

**MVP Delivery:** 90 days from approval to pilot readiness
- Read-only MVP (no autonomous fund movement)
- 8 specialized AI agents (not conversational chatbot)
- Async recommendation processing (5-minute maximum latency acceptable)
- SSE streaming for chat panel only

---

## Product Overview

### What the Backend Does

The backend is the **intelligence layer** sitting between cash data (from multiple sources) and treasury recommendations (approved by humans).

```
Banks / ERP / TMS / CSV / BAI2 / camt.053 / MT940
         ↓
    Data Ingestion (App Backend)
         ↓
  Validation & Normalization (App Backend → PostgreSQL)
         ↓
  Job Published to SQS
         ↓
  AI Agent Orchestration (AI Backend ← SQS)
         ↓
  Explainable Recommendations (AI Backend → MongoDB)
         ↓
  Result Polling (App Backend ← MongoDB)
         ↓
  Human Approval & Audit Trail (App Backend → PostgreSQL)
```

**Not a TMS replacement.** Core Cash works with or alongside existing Treasury Management Systems.

### Core Value Proposition

| Traditional Approach | Core Cash Approach |
|---|---|
| "Cash position is $5M" | "Cash position is $5M. At risk: $1.2M payroll due Friday. Recommend transfer $1.5M from UK entity. Why: eliminate shortfall. When: Thursday EOD. Control: policy OK, not restricted." |
| Forecast says $4M on day 7 | Forecast says $4M on day 7. Variance: $200K lower because collections delayed 2 days. Impact: may trigger borrowing need. |
| Treasury team interprets dashboards | AI recommends action with reasoning and alternatives. Treasury manager approves or overrides with audit trail. |

---

## Strategic Positioning

### Core Principles (Non-Negotiable — Unchanged from v1.0)

1. **Read-Only First**
   - MVP has zero autonomous fund movement
   - Every recommendation requires explicit human approval
   - No payment initiation, no transfers without authorization

2. **Explainability Required**
   - Every recommendation answers: Why? What? When? Control?
   - Reasoning trace stored in MongoDB for every agent run
   - Confidence scores on all recommendations

3. **Predictions ≠ Forecasts**
   - **Forecasts:** Model-driven (AR/AP schedules, historical patterns) — stored in MongoDB as `forecast` documents
   - **Predictions:** Pattern-based signals (anomaly detection, trend) — stored as separate `pattern_signals` documents
   - Never merged, never returned from the same endpoint

4. **Human-in-the-Loop**
   - Treasury manager always makes final decision
   - Approval workflow stored in PostgreSQL (audit trail)
   - Escalation path to CFO for edge cases

5. **Validated Data Gate**
   - AI Backend never reads raw bank files
   - AI Backend only reads PostgreSQL data that has passed parser → validation → normalization
   - AI Backend is read-only on PostgreSQL — no accidental writes possible

6. **Enterprise Security First**
   - Encryption at rest and in transit
   - Multi-factor authentication ready
   - 7-year audit log retention

---

## Scope & Constraints

### In-Scope for MVP

#### App Backend (Python / FastAPI)
- User auth (JWT validation from Cognito)
- RBAC (CFO, TreasuryManager, Analyst, Viewer)
- File upload and parsing (CSV, BAI2, camt.053, MT940) — **Excel excluded**
- PostgreSQL write path (accounts, statements, transactions)
- Account master and entity CRUD
- AR/AP schedule management
- Job publishing to SQS (triggers AI agents)
- Recommendation request endpoint (publishes job, returns request_id)
- Recommendation poll endpoint (reads MongoDB for status/result)
- Approval workflow (reads/writes approval status to PostgreSQL + MongoDB)
- Audit logging (all actions to audit_log table in PostgreSQL)
- Policy enforcement

#### AI Backend (Python / LangGraph)
- SQS job consumption (background worker)
- 8-agent LangGraph orchestration chain
- PostgreSQL read-only access (validated cash data)
- Claude 3.5 Sonnet LLM calls (Anthropic API) — **mocked in build sessions S0–S14; real wiring in dedicated S15 session**
- Recommendation generation (Why/What/When/Control)
- Forecast generation, variance explanation, CFO summary, pattern signals
- Result writing to MongoDB
- SSE streaming for chat panel

#### Shared Python Library
- All Pydantic request/response schemas
- SQS job envelope schemas (SQSJobMessage, SQSJobResult)
- Domain enums and type aliases
- Utility functions (dates, currency, formatting)
- Standard error codes and error response shapes

### Out-of-Scope for MVP

- ❌ Autonomous fund movement
- ❌ Payment initiation or SWIFT integration
- ❌ Direct bank APIs (file parsing only)
- ❌ Full TMS replacement
- ❌ Multi-tenant SaaS (single customer per deployment)
- ❌ Real-time intraday balances (daily refresh OK)
- ❌ Advanced ML forecasting (rule-based sufficient)
- ❌ Mobile app
- ❌ **Excel file parser** (CSV covers the same structured data use case)

---

## Backend Subsystems

### 1. Authentication & Authorization Service (App Backend)

**Responsibility:** Validate Cognito JWTs, enforce role-based access, track user context.

**Implementation (v2.0):**
- JWT validation via python-jose or PyJWT (using Cognito public keys, cached)
- Role extraction from `cognito:groups` claim
- FastAPI dependency injection (`Depends(get_current_user)`, `Depends(require_role(...))`)
- No session state — stateless JWT validation on every request

**API Endpoints:**
- `POST /auth/login` — Exchange Cognito authorization code for JWT (PKCE flow)
- `POST /auth/refresh` — Refresh expired JWT using refresh token
- `GET /auth/me` — Return current user profile and roles
- `POST /auth/logout` — Invalidate client-side token (server-side blacklist optional)

**Roles and Permissions:**

| Endpoint Category | Viewer | Analyst | TreasuryManager | CFO |
|---|---|---|---|---|
| Cash position (read) | ✅ | ✅ | ✅ | ✅ |
| File upload | ❌ | ✅ | ✅ | ✅ |
| Request recommendation | ❌ | ✅ | ✅ | ✅ |
| Approve recommendation | ❌ | ❌ | ✅ | ✅ |
| Manage accounts | ❌ | ❌ | ✅ | ✅ |
| Manage policy | ❌ | ❌ | ❌ | ✅ |
| View audit log | ❌ | ❌ | ✅ | ✅ |

**Non-Functional:**
- JWT validation: < 10 ms (local signature check, no network call)
- MFA: Cognito TOTP/SMS ready (config flag)

---

### 2. File Ingestion Service (App Backend)

**Responsibility:** Accept, validate, parse, and persist bank/ERP files.

**Implementation (v2.0):**
- Multipart file upload endpoint (FastAPI `UploadFile`)
- Store raw file to S3 (boto3)
- Parse using dedicated parsers (CSV, BAI2, camt.053, MT940)
- Write parsed data to PostgreSQL via SQLAlchemy async
- Track parse status in `source_files` table
- Publish `file_parsed` job to SQS if downstream agents need triggering

**API Endpoints:**
- `POST /api/files/upload` — Upload file (multipart/form-data)
- `GET /api/files/{id}/status` — Check parse status
- `GET /api/files` — List uploads (paginated)
- `DELETE /api/files/{id}` — Soft-delete (mark inactive)

**Parsers (all in Python):**
```
csv_parser.py     → Configurable column mapping; user selects date, amount, debit/credit columns
bai2_parser.py    → BAI2 balance reporting (North America standard)
camt053_parser.py → ISO 20022 XML end-of-day bank statement
mt940_parser.py   → SWIFT MT940 legacy format
```
**Note:** Excel (.xlsx) parser is explicitly excluded from MVP. Customers requiring Excel ingestion should export to CSV first.

**Non-Functional:**
- Parse time: < 30 sec for 100 MB file
- Error reporting: Row-level errors with clear messages
- Dry-run mode: Parse without committing (preview before insert)

---

### 3. Cash Position Service (App Backend)

**Responsibility:** Aggregate and serve consolidated cash position from PostgreSQL.

**Implementation (v2.0):**
- SQLAlchemy async queries (PostgreSQL)
- Aggregation by entity, bank, account, currency
- FX conversion to USD (daily rate from config/external source)
- Stale data detection (statement > 2 days old = warning)
- Results cached in-process (LRU cache, 1-hour TTL); invalidated on new file upload
- Only accounts with `include_in_cash_position = TRUE` included in totals
- `od_headroom` computed in service layer as `od_limit - od_utilised_amount` (never stored)

**API Endpoints:**
- `GET /api/cash-position/current` — Consolidated position (all entities)
- `GET /api/cash-position/by-entity/{entity_id}` — Single entity
- `GET /api/cash-position/by-date/{date}` — Historical position
- `GET /api/accounts` — List accounts (paginated)
- `POST /api/accounts` — Create account
- `PUT /api/accounts/{id}` — Update account
- `DELETE /api/accounts/{id}` — Soft-delete account

**Response Schema:**
```json
{
  "as_of_date": "2026-08-22T00:00:00Z",
  "consolidated": {
    "total_usd": 5250000,
    "total_by_entity": [
      {
        "entity_id": "uuid",
        "entity_name": "US HQ",
        "total_usd": 3000000,
        "accounts": [
          {
            "account_id": "uuid",
            "account_name": "Operating Account",
            "bank": "JPMorgan Chase",
            "currency": "USD",
            "closing_balance": 3000000,
            "available_balance": 2800000,
            "od_limit": null,
            "od_utilised": false,
            "od_headroom": null,
            "min_threshold": 2000000,
            "restricted_flag": false,
            "refresh_frequency": "Daily",
            "include_in_cash_position": true,
            "status": "Green",
            "statement_date": "2026-08-21",
            "hours_stale": 14
          }
        ]
      }
    ]
  },
  "warnings": [
    {
      "type": "stale_data",
      "account_id": "uuid",
      "message": "No statement since 2026-08-19 (3 days old)"
    }
  ]
}
```

---

### 4. Recommendation Service (App Backend + AI Backend)

**Responsibility (App Backend side):**
- Accept recommendation requests from frontend
- Validate and publish job to SQS
- Create pending record in MongoDB and reference row in PostgreSQL
- Serve poll endpoint (read result from MongoDB)
- Handle approval workflow (update MongoDB status + write to PostgreSQL audit trail)

**Responsibility (AI Backend side):**
- Consume SQS job
- Read validated cash data from PostgreSQL (read-only)
- Run 8-agent LangGraph chain
- Write full recommendation document to MongoDB (including reasoning trace)
- Update job status in MongoDB

**API Endpoints (App Backend):**
- `POST /api/recommendations/request` — Request recommendation (publishes to SQS)
- `GET /api/recommendations/{request_id}` — Poll status/result (reads MongoDB)
- `GET /api/recommendations` — List recommendations (paginated, filterable)
- `POST /api/recommendations/{id}/approve` — Approve (TreasuryManager/CFO only)
- `POST /api/recommendations/{id}/reject` — Reject with comment
- `POST /api/recommendations/{id}/override` — Override with manual action

**AI Endpoints (AI Backend):**
- `GET /ai/health` — AI backend health
- `GET /ai/chat/stream` — SSE chat streaming (frontend chat panel only)

**Job Message Format (via SQS):**
```json
{
  "job_id": "rec_20260822_001_a1b2c3d4",
  "job_type": "recommendation",
  "client_id": "uuid-client",
  "payload": {
    "cash_position_date": "2026-08-22",
    "policy_id": "policy_default"
  },
  "published_at": "2026-08-22T09:30:00Z"
}
```

**Recommendation Document (MongoDB — written by AI Backend):**
```json
{
  "job_id": "rec_20260822_001_a1b2c3d4",
  "client_id": "uuid-client",
  "status": "completed",
  "recommendation": {
    "why": "Payroll $2M due Friday; forecast shows $1.8M shortfall at current AR pace",
    "what": "Evaluate transfer of $2.2M from UK entity (surplus $4.5M) to US HQ",
    "when": "Thursday 3 PM ET (before 4 PM cut-off); value date Friday",
    "control": {
      "policy_check": "pass",
      "restricted_accounts_clear": true,
      "requires_approval": true,
      "approval_owner": "TreasuryManager"
    },
    "alternatives": [
      "Consider short-term borrowing against AR (~$50K interest if held 30 days)",
      "Review acceleration of customer collection calls (risk: relationship damage)"
    ],
    "confidence": 0.94
  },
  "reasoning_trace": [
    { "step": 1, "agent": "daily_cash", "duration_ms": 220, "status": "complete" },
    { "step": 2, "agent": "liquidity_risk", "duration_ms": 180, "status": "complete" },
    { "step": 3, "agent": "forecast", "duration_ms": 2100, "status": "complete" },
    { "step": 4, "agent": "policy_check", "duration_ms": 95, "status": "complete" },
    { "step": 5, "agent": "recommendation", "duration_ms": 9200, "status": "complete" }
  ],
  "created_at": "2026-08-22T09:30:00Z",
  "completed_at": "2026-08-22T09:31:05Z"
}
```

---

### 5. AI Agent Subsystem (AI Backend — LangGraph)

**Responsibility:** Orchestrate 8 agents using LangGraph state machine; produce structured outputs.

**Deployment note:** All 8 agents run in the AI Backend. Agent outputs are written to MongoDB. The App Backend polls via GET endpoints. Agents 4, 5, 6 use mock template responses in build sessions S0–S14; real Claude API is wired in dedicated session S15 post sign-off.

**Agent Chain (execution order, per agent-specifications-v2 numbering):**

```
Agent 1: Daily Cash Position
  Input:  client_id, cash_position_date
  Source: PostgreSQL (read-only)
  Output: Consolidated balances, stale data flags, od_headroom per account
  LLM:    No (deterministic query)

Agent 2: Forecast Intelligence
  Input:  Cash position + AR/AP schedule
  Source: PostgreSQL (read-only)
  Output: 7/30/60-day projections, confidence per day
  LLM:    No (rule-based calculation)
  Status: BLOCKED — opening balance anchor unresolved (pending decision with amit j)

Agent 3: Liquidity Risk
  Input:  Cash position + forecast
  Source: PostgreSQL policy table
  Output: Risk list with severity/urgency per risk
  LLM:    No (deterministic rule evaluation)

Agent 4: Policy Check
  Input:  Cash position + proposed action
  Source: PostgreSQL policy table
  Output: Policy pass/fail/warning per rule
  LLM:    No (deterministic)

Agent 5: Action Recommendation
  Input:  All prior agent outputs
  LLM:    YES — Claude 3.5 Sonnet (Why/What/When/Control) — MOCKED in S0–S14
  Output: Structured recommendation + alternatives + confidence

Agent 6: Variance Explanation
  Input:  Actual vs. forecast comparison
  LLM:    YES — Claude 3.5 Sonnet (driver explanation) — MOCKED in S0–S14
  Output: Driver breakdown, ranked by impact, with plain-English explanation
  Status: BLOCKED pending Agent 2 unblock

Agent 7: CFO Summary
  Input:  All prior agent outputs
  LLM:    YES — Claude 3.5 Sonnet (narrative composition) — MOCKED in S0–S14
  Output: Prose CFO summary (cash, risks, decisions, actions)

Agent 8: Treasury Continuity
  Input:  Current situation + historical precedents from MongoDB recommendations collection
  LLM:    YES — Claude 3.5 Sonnet (precedent matching) — MOCKED in S0–S14
  Output: "Previously in similar situations..." precedent callouts
```

**Non-Negotiable Agent Rules:**
- Agent 5 (Recommendation) MUST produce Why, What, When, Control — all four fields required; reject if any missing
- `what` field language MUST use evaluative verbs (Evaluate/Consider/Review/Propose/Escalate) — never action verbs (Transfer/Execute/Send/Move/Initiate)
- Agents 1–4 are deterministic — no LLM calls; results are reproducible
- Agents 5–8 use LLM — results include confidence score
- Forecast output (Agent 2) MUST NEVER be mixed with pattern signals output
- Pattern signals are a separate MongoDB collection, separate endpoint, separate UI component
- Variance tolerance: ±5% (not ±3%)

---

### 6. Forecast Service (App Backend + AI Backend)

**Responsibility (App Backend):** Accept forecast requests, publish to SQS, serve results.
**Responsibility (AI Backend):** Run forecast calculation (rule-based, Agent 2), store result in MongoDB.

**API Endpoints:**
- `POST /api/forecast/request` — Trigger async forecast generation → 202 `{ forecast_id, status: "queued" }`
- `GET /api/forecast/{forecast_id}` — Poll result
- `GET /api/forecast/current` — Latest completed forecast
- `PUT /api/forecast/{forecast_id}/assumptions` — Update manual assumptions
- `POST /api/forecast/variance/request` — Trigger async variance explanation → 202 `{ variance_id, status: "queued" }`
- `GET /api/forecast/variance/{variance_id}` — Poll variance result
- `GET /api/forecast/variance/current` — Latest variance explanation

---

### 7. Liquidity Risk Service (App Backend)

**Responsibility:** Serve current risk assessment (sourced from MongoDB after agent run).

**API Endpoints:**
- `GET /api/liquidity-risk/current` — Active risks
- `GET /api/liquidity-risk/alerts` — Critical + High severity only

---

### 8. Variance Explanation Service (AI Backend → MongoDB → App Backend)

**Responsibility:** Explain why actual cash differed from forecast (Agent 6).

**Status:** BLOCKED pending Agent 2 (Forecast) unblock.

**API Endpoints:**
- `POST /api/forecast/variance/request` — Request variance explanation (async)
- `GET /api/forecast/variance/{id}` — Poll for explanation
- `GET /api/forecast/variance/current` — Latest variance explanation

---

### 9. Executive Reporting (AI Backend → MongoDB → App Backend)

**Responsibility:** CFO summary + daily briefing (Agent 7 + Agent 8).

**API Endpoints:**
- `POST /api/cfo-summary/request` — Trigger async CFO summary → 202 `{ summary_id, status: "queued" }`
- `GET /api/cfo-summary/latest` — Latest CFO summary (sync read from MongoDB)
- `GET /api/cfo-summary/live-insights` — Polled every 60 minutes
- `GET /api/daily-briefing/latest` — Latest daily briefing

---

### 10. Audit & Approval Service (App Backend)

**Responsibility:** Record every action; manage approval workflow.

**Implementation:**
- AuditMiddleware logs every request (user_id, action, entity_type, entity_id, old/new value)
- PostgreSQL `audit_log` table (append-only, 7-year retention)
- Approval records in PostgreSQL `approvals` table
- Recommendation status synced between MongoDB (full doc) and PostgreSQL `recommendation_refs` (thin row for joins)

**API Endpoints:**
- `POST /api/recommendations/{id}/approve` — Approve (role-gated)
- `POST /api/recommendations/{id}/reject` — Reject with comment
- `GET /api/audit-log` — Query audit log (filterable)
- `GET /api/audit-log/export` — Download CSV/PDF

---

## Functional Requirements

### F1: User Authentication & Session Management

**User Story:** As a treasury manager, I want to log in securely so I can access Core Cash.

**Acceptance Criteria:**
- ✓ Frontend exchanges Cognito PKCE flow → receives JWT
- ✓ JWT stored in HTTP-only cookie (not localStorage)
- ✓ App Backend validates JWT on every request (< 10 ms, no network call)
- ✓ Token expires after 1 hour; refresh token extends session
- ✓ Role extracted from `cognito:groups` claim
- ✓ Logout invalidates client-side token

---

### F2: File Upload & Parsing

**User Story:** As a treasury manager, I want to upload bank statements and ERP extracts.

**Acceptance Criteria:**
- ✓ Support CSV, BAI2, camt.053, MT940 (**Excel excluded from MVP**)
- ✓ Raw file stored in S3 (versioned, encrypted)
- ✓ Column mapping UI for CSV (frontend; backend accepts mapping config)
- ✓ Parse errors reported per row (not silent failure)
- ✓ Dry-run mode: parse without commit
- ✓ Audit log: who uploaded, when, file size, row count, status

---

### F3: Cash Position Reporting

**User Story:** As a CFO, I want consolidated cash position across all entities.

**Acceptance Criteria:**
- ✓ Consolidated total (accounts with `include_in_cash_position = TRUE` only, converted to USD)
- ✓ Breakdown by entity, bank, account
- ✓ Multiple balance types (opening, closing, available, current)
- ✓ `od_headroom` returned per account (computed as `od_limit - od_utilised_amount`; null if no OD)
- ✓ Stale data warnings (statement > 2 days old)
- ✓ Historical position query (any past date)
- ✓ Query time < 500 ms (indexed PostgreSQL)

---

### F4: Liquidity Risk Detection

**User Story:** As a treasury manager, I want early alerts on liquidity risks.

**Acceptance Criteria:**
- ✓ Shortfall detection (forecast < threshold)
- ✓ Concentration detection (entity > 80% of total — separate entity-level rule)
- ✓ Stale data detection
- ✓ Threshold breach: **Yellow status when account balance ≥ 70% of `min_threshold` utilisation**; Red when at or below
- ✓ Severity levels: Critical, High, Medium, Low
- ✓ Urgency levels: Immediate, 1–7 days, 8–30 days
- ✓ Every risk links to a recommendation request

---

### F5: Cash Forecasting

**User Story:** As a CFO, I want a 7/30/60-day cash forecast.

**Acceptance Criteria:**
- ✓ 7, 30, 60-day projections (day-by-day for 7; weekly for 30; bi-weekly for 60)
- ✓ Drivers: AR schedule, AP schedule, recurring flows, historical patterns
- ✓ Manual assumption overrides (only assumptions with `confidence_pct >= 50` included)
- ✓ Three scenarios: base, bear, bull
- ✓ Confidence level per forecast day
- ✓ Variance tracking vs. actuals (±5% tolerance; variance outside ±5% flagged as unexplained)
- ✓ Forecast output NEVER mixed with pattern signal output
- ✓ Delivered async (POST /api/forecast/request → 202 → GET poll)

---

### F6: AI Recommendations

**User Story:** As a treasury manager, I want AI to recommend treasury actions.

**Acceptance Criteria:**
- ✓ Recommendation includes Why, What, When, Control (all 4 mandatory)
- ✓ `what` field uses evaluative language (Evaluate/Consider/Review/Propose/Escalate) — never action language (Transfer/Execute/Send/Move/Initiate)
- ✓ Confidence score (0.0–1.0)
- ✓ 2–3 alternatives with pros/cons
- ✓ Reasoning trace (step-by-step agent logs stored in MongoDB)
- ✓ Policy compliance check (every recommendation, Agent 8 blocks violations)
- ✓ Approval role gate (TreasuryManager or CFO only)
- ✓ Approval workflow (comment, timestamp, PostgreSQL audit log)
- ✓ Async delivery (POST /api/recommendations/request → 202 → GET poll; 5-minute max latency acceptable)
- ✓ Recommendation NEVER auto-executed (human approval always required)

---

### F7: Variance Explanation

**User Story:** As a CFO, I want to know why cash differed from forecast.

**Acceptance Criteria:**
- ✓ Compare actual vs. forecast balance
- ✓ Driver breakdown (AR, AP, FX, fees, payroll, taxes)
- ✓ Variance tolerance: ±5% (variance inside ±5% is expected and not escalated)
- ✓ Unexplained residual always surfaced explicitly — drivers never forced to sum to zero
- ✓ Ranked by impact (largest variance first)
- ✓ Confidence score per driver
- ✓ Plain-English explanation (LLM-composed, Agent 6)
- ✓ Stored in MongoDB as separate document from forecast
- ✓ Delivered async (POST /api/forecast/variance/request → 202 → GET poll)

---

### F8: Executive Reporting

**User Story:** As a CFO, I want a daily summary of cash position, risks, and decisions.

**Acceptance Criteria:**
- ✓ Daily briefing: prose narrative (not metrics dashboard)
- ✓ Sections: cash position (MTD change), key risks, pending decisions, action owners, outlook
- ✓ CFO Summary cash position section shows **MTD change** (not YTD)
- ✓ Exportable to PDF and printable
- ✓ Updated daily (morning scheduled job via SQS)
- ✓ Stored in MongoDB as `cfo_summaries` document
- ✓ `OD headroom` shown separately from usable cash (never merged)

---

### F9: Account Master Management

**User Story:** As an admin, I want to manage account hierarchy.

**Acceptance Criteria:**
- ✓ CRUD for accounts (entity, bank, account number, currency, type, threshold, restricted, od_limit, refresh_frequency, include_in_cash_position)
- ✓ Bulk CSV import
- ✓ Soft-delete (mark inactive)
- ✓ Audit log on every change
- ✓ Validation: account number unique per bank/client

---

### F10: Audit Logging & Compliance

**User Story:** As a compliance officer, I want a complete audit trail.

**Acceptance Criteria:**
- ✓ Every action logged: upload, query, recommendation request, approval, override
- ✓ Fields: user_id, timestamp, entity_type, entity_id, old_value, new_value, ip_address
- ✓ Append-only (no updates/deletes)
- ✓ Queryable by date, user, entity, action
- ✓ Exportable to CSV/PDF
- ✓ Retention: 7 years minimum (PostgreSQL + S3 archival)

---

## Non-Functional Requirements

### NFR1: Performance

| Metric | Target |
|---|---|
| Cash position query | < 500 ms |
| Recommendation delivery (P95) | < 5 minutes (async, SQS) |
| Forecast generation | < 30 sec (agent run) |
| Risk assessment (read from MongoDB) | < 500 ms |
| Approval record | < 1 sec |
| Audit log query | < 500 ms |
| File parse (100 MB) | < 30 sec |
| API P95 latency | < 2 sec |
| SSE chat first token | < 3 sec |

### NFR2: Scalability

| Dimension | Target |
|---|---|
| Concurrent users | 100+ |
| Recommendations per day | 500+ |
| Transactions in PostgreSQL | 10M+ |
| Accounts per customer | 1000+ |
| Entities per customer | 100+ |
| Daily file uploads | 1000+ |
| MongoDB recommendation documents | Unlimited (document store) |

### NFR3: Availability

| Metric | Target |
|---|---|
| Uptime SLA | 99.9% |
| RTO (Recovery Time Objective) | < 1 hour |
| RPO (Recovery Point Objective) | < 1 hour |
| RDS failover | < 1 minute (Multi-AZ) |
| ECS task replacement | < 2 minutes |
| SQS message durability | 99.999999999% |

### NFR4: Security

| Control | Requirement |
|---|---|
| Authentication | Cognito OIDC + JWT (RS256) |
| Authorization | RBAC (4 roles, enforced per endpoint) |
| PostgreSQL encryption at rest | AWS KMS (AES-256) |
| MongoDB encryption at rest | AES-256 (Atlas or DocumentDB) |
| S3 encryption | SSE-S3 or SSE-KMS |
| TLS in transit | TLS 1.2+ everywhere |
| Secrets management | AWS Secrets Manager (auto-rotation) |
| AI Backend PostgreSQL access | Read-only IAM user (SELECT only) |
| Audit log | Immutable, 7-year retention |

### NFR5: Schema Integrity

| Requirement | How Met |
|---|---|
| No schema drift between services | Shared Pydantic library (single source of truth) |
| API contract enforcement | Pydantic validation on every request/response |
| SQS message validation | SQSJobMessage schema in shared lib |
| MongoDB document shape | RecommendationDocument schema in shared lib |
| Breaking change detection | Shared lib version pinned in both services; CI fails if incompatible |

---

## API Specifications

### Base URLs

```
App Backend:  https://api.{customer}.core-cash.com
AI Backend:   https://ai.{customer}.core-cash.com  (SSE chat only)
```

### Authentication

```
All requests: Authorization: Bearer {JWT_TOKEN}
JWT from Cognito (PKCE flow)
Expires: 1 hour; refresh token: 30 days
HTTP-only cookie or Authorization header
```

### Standard Error Format

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Validation failed",
  "details": [
    { "field": "cash_position_date", "error": "Must be YYYY-MM-DD format" }
  ],
  "trace_id": "req_20260822_abc123"
}
```

### Status Codes

```
200 OK           — Succeeded
202 Accepted     — Job queued (async)
400 Bad Request  — Validation error
401 Unauthorized — Invalid JWT
403 Forbidden    — Insufficient role
404 Not Found    — Resource missing
429 Too Many Requests — Rate limited
500 Internal     — Unexpected error
503 Unavailable  — Transient (SQS/agent down)
```

### Rate Limiting

```
GET  requests: 1000/min per user
POST requests: 100/min per user
File uploads:  10/min per user
```

### Full Endpoint Inventory

**Auth:**
```
POST /auth/login
POST /auth/refresh
GET  /auth/me
POST /auth/logout
```

**Cash Position:**
```
GET  /api/cash-position/current
GET  /api/cash-position/by-entity/{entity_id}
GET  /api/cash-position/by-date/{date}
```

**Accounts:**
```
GET  /api/accounts
POST /api/accounts
PUT  /api/accounts/{id}
DELETE /api/accounts/{id}
POST /api/accounts/bulk-import
```

**Files:**
```
POST /api/files/upload
GET  /api/files
GET  /api/files/{id}/status
DELETE /api/files/{id}
```

**Recommendations:**
```
POST /api/recommendations/request        → 202 { request_id, status: "queued" }
GET  /api/recommendations/{request_id}   → poll until completed/failed
GET  /api/recommendations                → paginated list
POST /api/recommendations/{id}/approve
POST /api/recommendations/{id}/reject
POST /api/recommendations/{id}/override
```

**Forecast:**
```
POST /api/forecast/request               → 202 { forecast_id, status: "queued" }
GET  /api/forecast/{forecast_id}         → poll until completed/failed
GET  /api/forecast/current               → latest completed forecast
PUT  /api/forecast/{forecast_id}/assumptions
POST /api/forecast/variance/request      → 202 { variance_id, status: "queued" }
GET  /api/forecast/variance/{variance_id}→ poll until completed/failed
GET  /api/forecast/variance/current      → latest variance explanation
```

**Liquidity Risk:**
```
GET  /api/liquidity-risk/current
GET  /api/liquidity-risk/alerts
```

**CFO Summary & Briefing:**
```
POST /api/cfo-summary/request            → 202 { summary_id, status: "queued" }
GET  /api/cfo-summary/latest             → sync read from MongoDB
GET  /api/cfo-summary/live-insights      → polled every 60 minutes
GET  /api/daily-briefing/latest
```

**Trends:**
```
GET  /api/trends/overview
GET  /api/trends/patterns                ← pattern_signals (NEVER merged with forecasts)
GET  /api/trends/variance-history
```
**Note:** `/trends/predictions` is deferred to Phase 2. Pattern signals and forecasts are architecturally separate.

**Audit:**
```
GET  /api/audit-log
GET  /api/audit-log/export
```

**AI Backend:**
```
GET  /health
GET  /ai/chat/stream                     ← SSE (chat panel only)
```

---

## Data Model & Storage

### Two-Database Strategy

| Store | Technology | Owned By | Purpose |
|---|---|---|---|
| **PostgreSQL** | RDS Aurora | App Backend | Relational treasury data, approvals, audit log |
| **MongoDB** | Atlas M10 | AI Backend | Agent outputs, recommendations, history |

### PostgreSQL Tables (App Backend)

```
clients              — Client registry
legal_entities       — Entity hierarchy
banks                — Bank registry
accounts             — Account master (min_threshold, is_restricted, od_limit,
                       od_utilised_amount, refresh_frequency, include_in_cash_position)
statements           — Daily ending balances
transactions         — Individual movements
source_files         — Upload audit trail
ar_schedule          — Expected receipts
ap_schedule          — Expected payments
recommendation_refs  — Thin reference (job_id, status, client_id) for approval joins
approvals            — Approval decisions (who, when, comment)
audit_log            — Immutable action log
policies             — Control rules per client

Note: decision_log table DEFERRED TO PHASE 2.
      Agent 7 (Treasury Continuity) uses MongoDB recommendations collection for precedent lookup in MVP.
```

### MongoDB Collections (AI Backend)

```
recommendations      — Full recommendation documents with reasoning trace
agent_run_history    — Per-step agent logs
cfo_summaries        — Narrative executive summaries
daily_briefings      — Prose briefing content
pattern_signals      — SEPARATE from forecast; trend/anomaly detection
```

---

## Security & Compliance

### Auth Flow

```
1. User enters email/password in frontend
2. Frontend → Cognito (PKCE authorization code flow)
3. Cognito returns JWT + refresh token
4. Frontend stores JWT in HTTP-only cookie
5. Every App Backend request: validate JWT signature (Cognito public key, cached locally)
6. Extract: sub (user_id), cognito:groups (roles), client_id
7. AI Backend SSE: validate JWT same way (same Cognito issuer)
```

### Encryption

```
At Rest:
  PostgreSQL (RDS):  AWS KMS (AES-256)
  MongoDB (Atlas):   AES-256 at rest
  S3:                SSE-S3 (AES-256) or SSE-KMS

In Transit:
  All connections:   TLS 1.2+ minimum
  App → PostgreSQL:  SSL required
  App → MongoDB:     TLS 1.2+
  App → SQS:         HTTPS (AWS SDK)
  AI → PostgreSQL:   SSL required (read-only IAM user)
  AI → MongoDB:      TLS 1.2+
  AI → Anthropic:    HTTPS
```

### AI Backend Data Access Constraint

```
AI Backend PostgreSQL credentials:
  User: core_cash_readonly
  Grants: SELECT on all tables
  Revoked: INSERT, UPDATE, DELETE, DROP, TRUNCATE
  
This is enforced at the database level, not just application code.
Even if AI backend code has a bug, it cannot corrupt PostgreSQL data.
```

### Audit Logging

```
Every API request triggers AuditMiddleware:
  INSERT INTO audit_log (
    client_id, user_id, action, entity_type, entity_id,
    old_value, new_value, ip_address, created_at
  )

Examples:
  file_upload: who, when, filename, rows, parse status
  cash_query: who, when, date range
  recommendation_request: who, when, policy used
  recommendation_approved: who, when, comment
  policy_override: who, when, which rule, reason

Retention: 7 years (PostgreSQL hot storage 90 days → S3 Glacier archival)
Immutable: No UPDATE or DELETE on audit_log table (DB-level constraint)
```

---

## Performance & Scalability

### Caching Strategy (v2.0 — No Redis Required)

**Level 1: PostgreSQL Indexes**
```
(account_id, statement_date DESC)    — balance queries
(account_id, transaction_date DESC)  — transaction queries
(client_id, created_at DESC)         — audit log queries
(client_id, status)                  — recommendation status
```

**Level 2: In-Process Cache (App Backend)**
```python
from cachetools import TTLCache
cash_position_cache = TTLCache(maxsize=100, ttl=3600)
```

**Level 3: MongoDB Read**
```
Recommendation poll: Direct MongoDB lookup by job_id (indexed)
No additional caching needed — MongoDB document lookup is fast
```

### SQS Throughput

```
Standard queue: 3,000 messages/sec (unlimited with batching)
For MVP: ~100–500 recommendation jobs/day = negligible load
Visibility timeout: 300 sec (5 min) — covers worst-case agent run
DLQ: Catches failures after 3 retries
```

---

## Error Handling & Resilience

### SQS Job Failures

```
Agent run fails (exception):
  - AI Backend catches exception
  - Writes failure document to MongoDB: { status: "failed", error: "..." }
  - Does NOT delete SQS message (let visibility timeout expire)
  - SQS retries up to 3× (configurable via maxReceiveCount)
  - After 3 failures → moves to DLQ
  - CloudWatch alarm fires if DLQ depth > 0
  - On-call engineer inspects DLQ, decides to replay or discard

Frontend experience:
  - Poll returns { status: "failed", error: "Agent processing failed" }
  - User sees friendly message; can retry recommendation request
```

### App Backend If AI Backend Is Down

```
- App Backend publishes to SQS (job persisted, not lost)
- SQS retains message for 4 days
- When AI Backend recovers, it processes queued jobs
- Frontend poll shows "pending" until job processed
- No data loss; eventual consistency
```

### PostgreSQL Failover

```
Multi-AZ RDS: Automatic failover < 1 min
During failover: App Backend returns 503 (retry logic in SDK)
Connection pool: SQLAlchemy reconnects automatically
AI Backend read-only: Also fails; SQS job retried after recovery
```

---

## Integration Points

### Frontend ↔ App Backend (REST)

```
All standard API calls via REST/JWT
Frontend polls /api/recommendations/{id} every 5 seconds
Until status = "completed" or "failed"
```

### Frontend ↔ AI Backend (SSE — Chat Only)

```python
# ai-backend/app/routes/chat.py
@router.get("/ai/chat/stream")
async def chat_stream(message: str, session_id: str):
    async def generate():
        async with client.messages.stream(...) as stream:
            async for text in stream.text_stream:
                yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

### App Backend ↔ AI Backend (SQS — No Direct HTTP)

```
App Backend: sqs.send_message(...)    → publishes job
AI Backend:  sqs.receive_message(...) → consumes job
No direct HTTP calls between services
No shared secrets needed across services (each has own AWS IAM role)
```

### Shared Python Library Version Contract

```
Both services declare dependency on core-cash-shared:
  In monorepo: path = "../shared" (always in sync)
  As PyPI package: version pinned (e.g., ">=1.0.0,<2.0.0")

Breaking schema change process:
  1. Update shared lib (add field, change type)
  2. Bump version in pyproject.toml
  3. Update both services to handle new/old field
  4. Deploy shared lib, then both services
  5. Never deploy service with incompatible shared lib version
```

---

## Testing Strategy

### Unit Tests (Both Services)

```python
@pytest.mark.asyncio
async def test_request_recommendation_publishes_to_sqs():
    with patch("app.services.job_publisher.publish_job") as mock_publish:
        service = RecommendationService(mock_db, mock_mongo)
        result = await service.request_recommendation(
            client_id="client123",
            cash_position_date="2026-08-22",
            policy_id="policy_default"
        )
    assert result["status"] == "queued"
    assert "request_id" in result
    mock_publish.assert_called_once()
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_full_recommendation_flow(test_client, mock_sqs, mock_mongo):
    # 1. Upload file
    upload = await test_client.post("/api/files/upload", files={"file": sample_csv})
    assert upload.status_code == 202

    # 2. Request recommendation
    rec = await test_client.post("/api/recommendations/request", json={
        "cash_position_date": "2026-08-22",
        "policy_id": "policy_default"
    })
    assert rec.status_code == 202
    request_id = rec.json()["request_id"]

    # 3. Simulate AI backend completing the job (mock)
    await mock_mongo.recommendations.update_one(
        {"job_id": request_id},
        {"$set": {"status": "completed", "recommendation": {...}}}
    )

    # 4. Poll for result
    result = await test_client.get(f"/api/recommendations/{request_id}")
    assert result.json()["status"] == "completed"
    rec_data = result.json()["recommendation"]
    assert all(k in rec_data for k in ["why", "what", "when", "control"])

    # 5. Approve
    approval = await test_client.post(
        f"/api/recommendations/{request_id}/approve",
        json={"comment": "Approved"},
        headers={"X-Role": "TreasuryManager"}
    )
    assert approval.status_code == 200
```

### Schema Compatibility Tests

```python
def test_sqs_job_message_roundtrip():
    from core_cash_shared.schemas.jobs import SQSJobMessage
    msg = SQSJobMessage(
        job_id="rec_001",
        job_type="recommendation",
        client_id="client123",
        payload={"cash_position_date": "2026-08-22"},
        published_at="2026-08-22T09:00:00Z"
    )
    recovered = SQSJobMessage.model_validate_json(msg.model_dump_json())
    assert recovered.job_id == msg.job_id
```

---

## Success Metrics

### Product KPIs

| Metric | Target |
|---|---|
| Recommendation approval rate | ≥ 60% |
| Forecast accuracy (day 7) | Within ±5% of actual |
| Cash position accuracy | ≥ 99.5% vs. source |
| User daily active rate | ≥ 80% of treasury team |
| Risk detection rate | ≥ 95% (shortfalls caught before due date) |
| Time to recommendation | < 5 min (P95, async) |

### Technical KPIs

| Metric | Target |
|---|---|
| API uptime | 99.9% |
| P95 API latency | < 2 sec |
| SQS DLQ depth | 0 (alert if > 0) |
| MongoDB query time (poll) | < 200 ms |
| PostgreSQL query time | < 500 ms |
| Shared lib test coverage | ≥ 95% |
| App + AI backend test coverage | ≥ 80% |

---

## Out of Scope

- ❌ Autonomous fund movement (all actions require human approval)
- ❌ Payment initiation or SWIFT
- ❌ Direct bank APIs (file parsing only)
- ❌ Full TMS replacement
- ❌ Multi-tenant SaaS (single customer per deployment)
- ❌ Real-time intraday balances
- ❌ Advanced ML forecasting
- ❌ Mobile app
- ❌ **Excel file parser** — CSV covers the same structured data use case; excluded from MVP
- ❌ Real LLM wiring in build sessions S0–S14 (mock agents used; real Claude API wired in dedicated S15 session post Step-8 review)
- ❌ `/trends/predictions` endpoint (Phase 2)
- ❌ `decision_log` PostgreSQL table (Phase 2; MongoDB recommendations collection covers Agent 7 in MVP)

---

## Glossary

| Term | Definition |
|---|---|
| **App Backend** | Python/FastAPI service owning treasury ops, file ingestion, approvals |
| **AI Backend** | Python/FastAPI + LangGraph service owning agent orchestration, LLM calls |
| **Shared Lib** | Python package (core-cash-shared) containing Pydantic schemas used by both services |
| **SQS** | AWS Simple Queue Service — durable async job queue |
| **SQSJobMessage** | Pydantic schema defining the job envelope published to SQS |
| **LangGraph** | Agent orchestration framework (state machine for 8-agent chain) |
| **PostgreSQL** | Relational DB for treasury data (App Backend read/write; AI Backend read-only) |
| **MongoDB** | Document DB for agent outputs (AI Backend read/write; App Backend read for polling) |
| **Recommendation** | AI output answering Why/What/When/Control; requires human approval |
| **Forecast** | Model-driven 7/30/60-day projection (Agent 2 output) |
| **Pattern Signal** | Trend/anomaly detection result; NEVER merged with Forecast |
| **DLQ** | Dead-Letter Queue — receives SQS messages that failed 3× processing |
| **SSE** | Server-Sent Events — streaming protocol for chat panel only |
| **od_headroom** | Computed field: `od_limit - od_utilised_amount`; null if no OD arrangement; never stored |

---

## Approval

| Role | Name | Signature | Date |
|---|---|---|---|
| **Product Manager** | [TBD] | | |
| **Engineering Lead** | [TBD] | | |
| **Security Officer** | [TBD] | | |

---

**Document Version:** 2.1
**Supersedes:** v2.0 (August 22, 2026)
**Last Updated:** August 22, 2026
**Changes in v2.1:** Excel removed from F2 and added to Out of Scope; F4 threshold language clarified (70% Yellow status); F5 variance tolerance explicitly ±5%; F7 unexplained residual rule added; F8 MTD change and OD headroom separation noted; `od_headroom` added to F3 response schema; `decision_log` deferred note added; evaluative language constraint added to F6; Agent 2/6 blocked status noted; `/trends/predictions` deferral confirmed.
**Status:** Ready for Development