# Architecture Overview

## 1. What Core Cash Agent Is (and Is Not)

**Core Cash Agent is an AI intelligence layer**, not a Treasury Management System (TMS) replacement.

### What It Does:
- Analyzes cash position, liquidity risk, and forecast scenarios
- Generates actionable recommendations for treasury team
- Learns from bank data (BAI2, MT940, camt.053), AR/AP schedules, and manual assumptions
- Explains why forecasts differ from actuals (variance analysis)
- Provides executive briefings for CFO decision-making

### What It Does NOT Do:
- Execute transactions autonomously
- Transfer funds, approve payments, or initiate wire transfers
- Modify external systems without human approval
- Store unencrypted sensitive data (all passwords/tokens read from environment only)
- Replace human judgment — all recommendations require explicit approval

### The Human-in-the-Loop Model:
1. **Read-only pipeline**: Core Cash pulls data from bank feeds, AR/AP systems
2. **AI analysis**: 8-agent pipeline scores risks, detects shortfalls, ranks recommendations
3. **Recommendation only**: Agent 4 (Action Recommendation) generates suggestions
4. **Human approval**: Treasury Manager or CFO reviews and approves/rejects each recommendation
5. **Audit trail**: Every decision logged; no autonomous execution under any circumstance

---

## 2. Monorepo Structure

```
Core-Cash-Treasury-Backend/
│
├── shared/                          ← core-cash-shared pip package
│   ├── core_cash_shared/
│   │   ├── __init__.py
│   │   ├── enums.py                ← JobType, JobStatus, ApprovalStatus
│   │   ├── error_codes.py          ← AUTH_*, VALIDATION_*, JOB_*, etc.
│   │   └── schemas/                ← Pydantic models
│   │       ├── errors.py           ← ErrorDetail, ErrorResponse
│   │       ├── jobs.py             ← JobEnvelope, JobStatus schema
│   │       ├── bank_statement.py   ← Statement parsing schemas
│   │       ├── chat.py             ← Chat message/event schemas
│   │       ├── forecast.py         ← ForecastDayRow, ForecastResult
│   │       └── variance.py         ← Variance explanation schemas
│   └── setup.py                    ← pip package metadata
│
├── app-backend/                     ← Primary FastAPI service (port 8000)
│   ├── app/
│   │   ├── main.py                 ← FastAPI app setup, middleware, routers
│   │   ├── config.py               ← Environment variables, database URLs
│   │   ├── database.py             ← SQLAlchemy engine, AsyncSession
│   │   ├── auth/                   ← JWT validation, RBAC
│   │   │   ├── jwt.py              ← RS256 token validation
│   │   │   ├── dependencies.py     ← get_current_user, require_role
│   │   │   └── models.py           ← UserModel with roles
│   │   ├── models/                 ← SQLAlchemy ORM models
│   │   │   ├── legal_entity.py
│   │   │   ├── bank_accounts.py
│   │   │   ├── bank_statement.py
│   │   │   ├── ar_data.py
│   │   │   ├── ap_data.py
│   │   │   ├── manual_assumption.py
│   │   │   ├── job_status.py
│   │   │   ├── audit_log.py
│   │   │   ├── system_config.py
│   │   │   ├── fx_rates.py
│   │   │   ├── investment_policy.py
│   │   │   └── source_file.py
│   │   ├── routers/                ← FastAPI route modules
│   │   │   ├── forecast.py         ← GET /api/forecast/*, POST assumptions
│   │   │   ├── recommendations.py  ← POST request, approve, reject, override
│   │   │   ├── variance.py         ← GET /api/forecast/variance/*
│   │   │   ├── cfo_summary.py      ← GET /api/cfo/* (briefing, export)
│   │   │   └── chat_proxy.py       ← POST /api/chat/stream (SSE proxy to AI Backend)
│   │   ├── routes/                 ← Additional routes (accounts, entities, config, files, audit, metadata)
│   │   ├── jobs/                   ← Job publishing & registry
│   │   │   ├── interface.py        ← JobPublisher ABC
│   │   │   ├── in_process.py       ← InProcessJobPublisher (dev/MVP)
│   │   │   └── registry.py         ← Job type mappings
│   │   ├── services/               ← Business logic
│   │   │   ├── csv_parsers/        ← CSV parsers (AR, AP, bank balance)
│   │   │   ├── file_parsers/       ← Bank statement parsers (BAI2, MT940, camt.053)
│   │   │   ├── audit_service.py    ← write_audit_event
│   │   │   ├── recommendation_service.py ← approve_recommendation, etc.
│   │   │   └── cache.py            ← Simple in-memory cache
│   │   ├── middleware/
│   │   │   └── audit_middleware.py ← Captures user_id for audit_log
│   │   └── mongo/                  ← MongoDB connection
│   │       └── client.py           ← get_mongo_db, MongoClient
│   ├── alembic/                    ← SQL migrations
│   │   ├── versions/               ← Migration files (001_*.py, 002_*.py, etc.)
│   │   └── env.py, alembic.ini     ← Alembic config
│   ├── tests/
│   ├── .env.example
│   ├── requirements.txt
│   └── Dockerfile
│
├── ai-backend/                     ← AI FastAPI service (port 8001)
│   ├── app/
│   │   ├── main.py                 ← FastAPI app, read-only PostgreSQL, MongoDB R/W
│   │   ├── config.py               ← Environment variables
│   │   ├── database.py             ← Read-only PostgreSQL connection
│   │   ├── agents/                 ← Agent implementations
│   │   │   ├── base.py             ← AgentBase, AgentState
│   │   │   ├── daily_cash_position.py ← Agent 1
│   │   │   ├── forecast.py         ← Agent 2 (Session 13)
│   │   │   ├── liquidity_risk.py   ← Agent 3
│   │   │   ├── policy_control.py   ← Agent 7 (policy checks)
│   │   │   ├── action_recommendation.py ← Agent 4 (mocked LLM)
│   │   │   ├── variance_explanation.py ← Agent 5 (mocked LLM)
│   │   │   ├── cfo_summary.py      ← Agent 6 (mocked LLM)
│   │   │   └── treasury_continuity.py ← Agent 8 (policy enforcement)
│   │   ├── jobs/                   ← Job handlers
│   │   │   ├── registry.py         ← JOB_REGISTRY (maps job_type → handler)
│   │   │   ├── forecast_job.py     ← run_forecast_job handler
│   │   │   └── *.py                ← Other job handlers
│   │   ├── routes/                 ← Health, Chat (SSE streaming)
│   │   │   ├── health.py
│   │   │   └── chat.py             ← POST /chat/stream (EventSourceResponse)
│   │   ├── sqs/                    ← SQS consumer (production) / InProcess (dev)
│   │   │   └── consumer.py         ← Consumer loop, fetches jobs, runs handlers
│   │   └── mongo/
│   │       └── client.py           ← get_mongo_db, MongoClient
│   ├── tests/
│   ├── .env.example
│   ├── requirements.txt
│   └── Dockerfile
│
└── docs/
    └── developer-guide/            ← THIS DIRECTORY
        ├── 01-architecture.md      ← This file
        ├── 02-database-schema.md
        ├── 03-api-reference.md
        ├── 04-repo-structure.md
        ├── 05-config-and-env.md
        ├── 06-frontend-integration-guide.md
        └── README.md
```

### Why Two Services?

| Aspect | App Backend (port 8000) | AI Backend (port 8001) |
|--------|-------------------------|------------------------|
| **Write Access** | PostgreSQL only | MongoDB + LLM API only |
| **Read Access** | PostgreSQL + MongoDB | PostgreSQL (read-only) |
| **Role** | User-facing API, job publishing | Agent pipeline, analysis |
| **Uptime Requirement** | Critical (user dashboard) | High (async processing) |
| **Scaling** | Horizontal (stateless) | Horizontal per agent |

---

## 3. The 8-Agent Pipeline

Each agent runs asynchronously as part of a job. The pipeline is **non-deterministic** — agents may run in parallel or sequentially depending on job type.

### Agent 1: Daily Cash Position (Session 3)
- **Input**: bank_statement (latest balance_after), bank_accounts.balance_override
- **Output**: cash_positions (MongoDB)
- **Calculation**: Sums account balances, applies FX conversion, filters by include_in_cash_position = TRUE
- **Blocking**: None (always produces a result)
- **Real vs. Mocked**: Real Python calculation (no LLM)

### Agent 2: Forecast (Session 13)
- **Input**: bank_statement (opening balance), manual_assumptions, system_config.forecast_confidence_threshold
- **Output**: forecast_runs (MongoDB), agent_2_signals (MongoDB if shortfall detected)
- **Calculation**: Projects 30-day cash flows from manual assumptions, calculates confidence bands (±15% placeholder)
- **Blocking**: If bank_statement.balance_after is NULL → data_status = "blocked", OPENING_BALANCE_UNRESOLVED
- **Real vs. Mocked**: Real calculation for assumption-based forecast; ML model placeholder (post-MVP)

### Agent 3: Liquidity Risk (Session 4)
- **Input**: cash_positions, investment_policy, agent_2_signals (shortfall detection)
- **Output**: liquidity_risk (MongoDB with shortfall_pts, warning_threshold_pct = 70%)
- **Calculation**: Scores cash adequacy, compares against policy cutoff, flags shortfalls
- **Blocking**: None (returns scores even if forecast blocked)
- **Real vs. Mocked**: Real scoring logic (no LLM)

### Agent 4: Action Recommendation (Session 6)
- **Input**: liquidity_risk, cash_positions, investment_policy, cfo_summary (state)
- **Output**: recommendations (MongoDB)
- **Recommendations**: Invest surplus, draw credit line, increase AR collection efforts
- **Blocking**: None (always produces mocked recommendations in MVP)
- **Real vs. Mocked**: **Mocked LLM** (returns fixed response; Session 15 wires real Claude API)

### Agent 5: Variance Explanation (Session 10)
- **Input**: forecast_runs (from Agent 2), bank_statement (actuals), ar_data, ap_data
- **Output**: variance_explanations (MongoDB), updates forecast_runs.forecast_accuracy_pct
- **Calculation**: Explains why forecast differed from actuals (e.g., "AR delayed by 3 days")
- **Blocking**: If forecast_runs.data_status = "blocked" → no variance (nothing to explain)
- **Real vs. Mocked**: **Mocked LLM** (returns template responses; Session 15 wires real Claude API)

### Agent 6: CFO Summary (Session 9)
- **Input**: cash_positions, liquidity_risk, recommendations, forecast_outlook
- **Output**: cfo_reports (MongoDB)
- **Summary**: Executive brief (top 5 risks, 3 recommendations, week-ahead forecast)
- **Blocking**: None (generates summary even if incomplete data)
- **Real vs. Mocked**: **Mocked LLM** (returns fixed summary structure; Session 15 wires real Claude API)

### Agent 7: Treasury Continuity / Policy Control (Session 9)
- **Input**: investment_policy, investment_cutoff, recommendations
- **Output**: policy_violations (internal state)
- **Validation**: Enforces investment limits, cutoff rules, counterparty exposure
- **Blocking**: If violations → recommendation blocked (approval_status = "Blocked")
- **Real vs. Mocked**: Real validation logic (no LLM)

### Agent 8: Daily Briefing (Session 6)
- **Input**: cfo_reports, cash_positions, liquidity_risk
- **Output**: daily_briefings (MongoDB)
- **Format**: Time-series snapshots for dashboard/email delivery
- **Blocking**: None (always generates from latest data)
- **Real vs. Mocked**: Real aggregation (no LLM)

---

## 4. Request Lifecycle

### Async Job Pattern (Forecast, Recommendations, Variance, etc.)

```
1. Frontend → POST /api/recommendations/request
   ↓
2. App Backend creates JobStatus (status=queued)
   ↓
3. App Backend publishes JobEnvelope to InProcessJobPublisher
   ↓
4. AI Backend consumer loop dequeues job
   ↓
5. AI Backend spawns agent (e.g., ForecastAgent)
   ↓
6. Agent runs, writes result to MongoDB
   ↓
7. AI Backend updates JobStatus (status=completed, result_id=mongo_doc_id)
   ↓
8. Frontend polls GET /api/recommendations/{request_id}
   ↓
9. App Backend retrieves JobStatus → if completed, fetches MongoDB result
   ↓
10. Frontend displays recommendation with reasoning_trace
```

**HTTP Status Codes:**
- `202 Accepted`: Job queued (POST /api/*/request)
- `200 OK`: Job completed, result available
- `202 Accepted`: Still processing (GET polling)
- `404 Not Found`: Job not found
- `500 Internal Error`: Agent failed (result_id=null, status=failed)

**Polling Recommendation:**
- Poll interval: 2 seconds
- Max timeout: 60 seconds
- Most agents complete in 1–30 seconds

### Chat Pattern (Different: SSE Streaming)

```
1. Frontend → POST /api/chat/stream
   ↓
2. App Backend (chat_proxy.py) forwards to AI Backend
   ↓
3. AI Backend (chat.py) opens SSE stream
   ↓
4. Sends event: context (treasury data snapshot)
   ↓
5. Sends event: token (LLM output chunks)
   ↓
6. Sends event: done (stream ends)
   ↓
7. Frontend renders streaming response in real-time
```

**No job queue**: Chat is synchronous, read-only, real-time.

---

## 5. Authentication Flow

### JWT Token Acquisition

1. **Frontend**: Redirects to AWS Cognito login
2. **Cognito**: Issues JWT (signed with RS256 private key)
3. **Frontend**: Stores JWT; includes in every API call: `Authorization: Bearer <token>`
4. **App Backend**: Validates JWT signature using Cognito public key (app/auth/jwt.py)
5. **AI Backend**: Also validates independently (no token passed; reads from PostgreSQL if needed)

### Token Structure

```json
{
  "sub": "user-uuid",
  "email": "alice@company.com",
  "cognito:groups": ["TreasuryManager"],
  "exp": 1693507200,
  "iat": 1693503600
}
```

### RBAC Roles

| Role | Can Approve | Can Request | Can Upload Files | Can View Audit |
|------|-------------|-------------|------------------|----------------|
| **Viewer** | ❌ | ❌ | ❌ | ✅ |
| **Analyst** | ❌ | ✅ (request) | ✅ | ✅ |
| **TreasuryManager** | ✅ (approve/reject) | ✅ | ✅ | ✅ |
| **CFO** | ✅ (approve/reject) | ✅ | ✅ | ✅ |

**Enforcement:**
- `@require_role(["TreasuryManager", "CFO"])` decorator on endpoints
- Raises `403 Forbidden` if user lacks required role
- Audit middleware logs user_id from JWT

---

## 6. Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Browser)                        │
└──────────────────┬───────────────────────────────────────────────┘
                   │ JWT Auth: Bearer token
                   ↓
┌──────────────────────────────────────────────────────────────────┐
│                    APP BACKEND (port 8000)                        │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Routes: /api/cash-position, /api/recommendations, etc.      │ │
│  │ Auth: JWT RS256 validation                                  │ │
│  │ RBAC: require_role decorator                                │ │
│  │ Audit: AuditMiddleware captures user_id                     │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Read/Write PostgreSQL:                                       │ │
│  │ • bank_statement (latest balance)                           │ │
│  │ • manual_assumptions (CRUD)                                 │ │
│  │ • job_status (tracks request ID)                            │ │
│  │ • audit_log (all user actions)                              │ │
│  │ • system_config (forecast threshold, warning %, etc.)       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Read MongoDB:                                                │ │
│  │ • Poll forecast_runs, recommendations for job results       │ │
│  │ • Get latest cash_positions, liquidity_risk                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────┬───────────────────────────────────────────────┘
                   │
         ┌─────────┴──────────┬─────────────────┐
         ↓                    ↓                 ↓
    ┌─────────┐         ┌──────────┐    ┌────────────────┐
    │  Publish│         │ Read for │    │   Read for     │
    │   Job   │         │ polling  │    │   dashboard    │
    │Envelope │         │ results  │    │   data (R/O)   │
    └────┬────┘         └──────────┘    └────────────────┘
         │
    ┌────┴──────────────────────────────────────────────────────────┐
    │      InProcessJobPublisher (Dev) / SQS (Production)           │
    └────┬──────────────────────────────────────────────────────────┘
         │
         ↓
┌──────────────────────────────────────────────────────────────────┐
│                    AI BACKEND (port 8001)                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Job Consumer Loop: Dequeue, route to handler                │ │
│  │ Handlers: forecast_job.py, recommendation_job.py, etc.      │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Agents (Read-Only PostgreSQL):                               │ │
│  │ • Agent 1: Daily Cash Position                              │ │
│  │ • Agent 2: Forecast (Session 13)                            │ │
│  │ • Agent 3: Liquidity Risk                                   │ │
│  │ • Agent 4: Action Recommendation (mocked LLM)               │ │
│  │ • Agent 5: Variance Explanation (mocked LLM)                │ │
│  │ • Agent 6: CFO Summary (mocked LLM)                         │ │
│  │ • Agent 7: Treasury Continuity (policy validation)          │ │
│  │ • Agent 8: Daily Briefing                                   │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Write MongoDB:                                               │ │
│  │ • forecast_runs (Agent 2)                                   │ │
│  │ • agent_2_signals (Agent 2 shortfall detection)             │ │
│  │ • liquidity_risk (Agent 3)                                  │ │
│  │ • recommendations (Agent 4)                                 │ │
│  │ • variance_explanations (Agent 5)                           │ │
│  │ • cfo_reports (Agent 6)                                     │ │
│  │ • daily_briefings (Agent 8)                                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Chat SSE Endpoint (Real-time streaming):                     │ │
│  │ • POST /chat/stream → EventSourceResponse                   │ │
│  │ • Event: context, token, done, error                        │ │
│  └─────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘

PostgreSQL ◄─────────────────────────────────────────── App Backend
│                                                       (Read/Write)
└────────────────────── AI Backend
                        (Read-Only)

MongoDB  ◄──────────────────────────────────────────── AI Backend (R/W)
         ├────────────── App Backend (R/O for polling)
         └────────────── Chat Proxy (R/O for display)
```

---

## Summary

Core Cash Agent is a **read-only, human-approved** intelligence layer built on two services:

1. **App Backend (Port 8000)**: User-facing API, JWT auth, PostgreSQL state, job publishing
2. **AI Backend (Port 8001)**: Agent pipeline, MongoDB analytics, LLM integration (Session 15)

The **8-agent pipeline** runs asynchronously, producing MongoDB documents that App Backend polls and serves to the frontend. No autonomous execution—every recommendation requires explicit approval.

Next: [Database Schema Reference →](02-database-schema.md)
