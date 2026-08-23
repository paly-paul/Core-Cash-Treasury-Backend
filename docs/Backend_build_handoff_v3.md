# Core Cash — Backend Build Handoff

**Version**: 3.0
**Date**: 22 August 2026
**Status**: S0–S6 build-ready. S7/S14 blocked (opening balance). S15 post-sign-off.
**Changes from v2.0**: Complete rewrite for dual-service architecture (App Backend + AI Backend). Single-service Steps 2–8 replaced by S0–S15 Claude Code sessions. SQS async job queue, LangGraph state machine, MongoDB for agent outputs, shared Python library all introduced.
**Audience**: Backend engineers building S0–S15

---

## How to Use This Document

1. Read this document in full before starting any session.
2. Read `agent-specifications-v2.md` for the exact output shape of each agent.
3. Read `api-contract-v3.md` for the exact endpoint request/response shapes — both services.
4. Read `financial-business-logic-v2.md` for calculation rules.
5. Build **one session at a time**. Stop at each checkpoint. Do not start the next session without review sign-off.
6. Never deviate from `api-contract-v3.md` without flagging first — frontend depends on both base URLs.
7. LLM calls (Agents 4, 5, 6) are mocked in all sessions except S15. Do not wire the real Anthropic API before S15.

---

## Architecture Overview

Core Cash has **two FastAPI services** that must be built together:

| Service | Base URL | Role |
|---|---|---|
| **App Backend** | `https://api.{customer}.core-cash.com` | Auth, file uploads, config, data ingestion, user-facing CRUD, polling endpoints |
| **AI Backend** | `https://ai.{customer}.core-cash.com` | LangGraph agent orchestration, agent job execution, MongoDB writes, SSE chat |

**Communication pattern**:
- App Backend publishes jobs to **AWS SQS** (Standard queue)
- AI Backend consumes jobs from SQS, runs the agent pipeline, writes outputs to **MongoDB**
- Frontend polls App Backend GET endpoints; App Backend reads MongoDB for agent output
- AI Backend has **read-only** access to PostgreSQL (SELECT-only IAM user, enforced at DB level)
- App Backend has read/write access to PostgreSQL

**Data stores**:
- **PostgreSQL** (RDS Aurora): accounts, statements, uploads, auth, config — App Backend R/W; AI Backend R/O
- **MongoDB** (Atlas M10): agent outputs, recommendation history — AI Backend R/W; App Backend R/O
- **AWS SQS**: async job queue (Standard, 300s visibility timeout, DLQ after 3 retries)

**Shared library**:
- `core-cash-shared` (Python package, built in S0)
- Contains: Pydantic schemas, SQS job envelope, error codes, domain enums
- Both services install it as a local dependency

---

## Session Build Order

| Session | What Gets Built | Status |
|---|---|---|
| **S0** | `core-cash-shared` — shared Pydantic schemas + SQS envelope | ✅ Build-ready |
| **S1** | App Backend scaffold — FastAPI, PostgreSQL, JWT auth, ORM models | ✅ Build-ready |
| **S2** | AI Backend scaffold — FastAPI, SQS consumer, LangGraph skeleton, MongoDB | ✅ Build-ready |
| **S3** | DB migrations + Agent 1 (Daily Cash Position) + Accounts endpoints | ✅ Build-ready |
| **S4** | Agent 3 (Liquidity Risk) + risk endpoints | ✅ Build-ready |
| **S5** | CSV parsers — bank balances, AR data, AP data | ✅ Build-ready |
| **S6** | Agent 4 (Action Recommendation, mocked) + Agent 8 (Policy Control) | ✅ Build-ready |
| **S7** | Forecast scaffold (pre-work only — BLOCKED) | ⛔ Blocked |
| **S8** | Config/FX endpoints — FX rates, investment policy, cutoffs | ✅ Build-ready |
| **S9** | Agents 6 (CFO Summary, mocked) + 7 (Treasury Continuity) | ✅ Build-ready |
| **S10** | Agent 5 (Variance Explanation, mocked) | ✅ Build-ready |
| **S11** | Audit log + Approvals workflow | ✅ Build-ready |
| **S12** | Chat SSE endpoint (AI Backend) | ✅ Build-ready |
| **S13** | BAI2 / camt.053 / MT940 parsers | ✅ Build-ready |
| **S14** | Forecast unblock — Agent 2 full implementation | ⛔ Blocked (until opening balance rule confirmed) |
| **S15** | Real LLM wiring — Agents 4, 5, 6 | 🔒 Post Step 8 sign-off only |

---

## S0: Shared Python Library (`core-cash-shared`)

**Status**: ✅ Build-ready.

**Repo**: `core-cash-shared/` — separate repo, published as a local pip-installable package. Both App Backend and AI Backend add it as `pip install -e ../core-cash-shared`.

**What to build**:

```
core-cash-shared/
├── pyproject.toml
├── core_cash_shared/
│   ├── __init__.py
│   ├── enums.py           # Domain enumerations
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── accounts.py    # Account, Statement Pydantic schemas
│   │   ├── agents.py      # Agent output schemas (CashPositionOutput, etc.)
│   │   ├── jobs.py        # SQS job envelope
│   │   └── errors.py      # Structured error response schema
│   └── error_codes.py     # Central error code registry
```

**`enums.py`** — define and export:
```python
from enum import Enum

class AccountStatus(str, Enum):
    GREEN = "Green"
    YELLOW = "Yellow"
    RED = "Red"

class JobType(str, Enum):
    CASH_POSITION = "cash_position"
    LIQUIDITY_RISK = "liquidity_risk"
    ACTION_RECOMMENDATION = "action_recommendation"
    VARIANCE_EXPLANATION = "variance_explanation"
    CFO_SUMMARY = "cfo_summary"
    TREASURY_CONTINUITY = "treasury_continuity"

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class ApprovalStatus(str, Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"

class RefreshFrequency(str, Enum):
    DAILY = "Daily"
    WEEKLY = "Weekly"
    MONTHLY = "Monthly"
    MANUAL = "Manual"

class DataConfidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

class RiskLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
```

**`schemas/jobs.py`** — SQS job envelope (both services must use this exactly):
```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
from ..enums import JobType, JobStatus

class JobEnvelope(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_type: JobType
    client_id: str
    user_id: str
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    payload: Dict[str, Any] = Field(default_factory=dict)
    # payload contents vary by job_type; document in api-contract-v3.md

class JobStatusResponse(BaseModel):
    request_id: str
    status: JobStatus
    job_type: JobType
    requested_at: datetime
    completed_at: Optional[datetime] = None
    result_id: Optional[str] = None   # MongoDB document _id when completed
    error: Optional[str] = None
```

**`schemas/errors.py`**:
```python
from pydantic import BaseModel
from typing import Optional

class ErrorDetail(BaseModel):
    code: str          # e.g. "OPENING_BALANCE_UNRESOLVED"
    message: str
    severity: str      # "error" | "warning"
    field: Optional[str] = None

class ErrorResponse(BaseModel):
    error: ErrorDetail
```

**`error_codes.py`** — central registry, both services import from here:
```python
# Authentication
AUTH_TOKEN_MISSING = "AUTH_TOKEN_MISSING"
AUTH_TOKEN_INVALID = "AUTH_TOKEN_INVALID"
AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
AUTH_PERMISSION_DENIED = "AUTH_PERMISSION_DENIED"

# Validation
VALIDATION_REQUIRED_FIELD = "VALIDATION_REQUIRED_FIELD"
VALIDATION_INVALID_FORMAT = "VALIDATION_INVALID_FORMAT"
VALIDATION_FILE_TOO_LARGE = "VALIDATION_FILE_TOO_LARGE"
VALIDATION_UNSUPPORTED_FORMAT = "VALIDATION_UNSUPPORTED_FORMAT"

# Business logic
OPENING_BALANCE_UNRESOLVED = "OPENING_BALANCE_UNRESOLVED"
FX_RATE_MISSING = "FX_RATE_MISSING"
INVESTMENT_POLICY_NOT_UPLOADED = "INVESTMENT_POLICY_NOT_UPLOADED"
ACCOUNT_RESTRICTED = "ACCOUNT_RESTRICTED"

# Jobs
JOB_NOT_FOUND = "JOB_NOT_FOUND"
JOB_STILL_PROCESSING = "JOB_STILL_PROCESSING"
JOB_FAILED = "JOB_FAILED"

# Data
DATA_STALE = "DATA_STALE"
DATA_MISSING_FEED = "DATA_MISSING_FEED"
```

**Stop-and-review checklist**:
- [ ] `pyproject.toml` has correct package name `core-cash-shared` with version `0.1.0`
- [ ] Both App Backend and AI Backend can `pip install -e ../core-cash-shared` without conflict
- [ ] `JobEnvelope` imports without error in both service contexts
- [ ] All enums exported from `__init__.py`
- [ ] At least one import test from a scratch Python script

---

## S1: App Backend Scaffold

**Status**: ✅ Build-ready.

**Repo**: `core-cash-app/`

**What to build**:

```
core-cash-app/
├── pyproject.toml           # depends on core-cash-shared
├── .env.example
├── app/
│   ├── main.py              # FastAPI app, routers, CORS, middleware
│   ├── config.py            # Settings via pydantic-settings
│   ├── database.py          # SQLAlchemy engine + session factory
│   ├── auth/
│   │   ├── jwt.py           # Cognito RS256 JWT validation
│   │   ├── dependencies.py  # get_current_user, require_role
│   │   └── models.py        # User Pydantic model
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── client.py
│   │   ├── legal_entity.py
│   │   ├── bank.py
│   │   ├── account.py
│   │   ├── statement.py
│   │   ├── transaction.py
│   │   ├── source_file.py
│   │   └── users.py
│   ├── sqs/
│   │   ├── client.py        # Boto3 SQS publisher
│   │   └── publisher.py     # publish_job(envelope: JobEnvelope) -> str
│   ├── mongo/
│   │   └── client.py        # Motor AsyncIOMotorClient, db accessor
│   ├── routes/
│   │   └── health.py        # GET /health
│   └── utils/
│       └── fixtures.py      # Mock data seed
```

**Key implementation rules**:

JWT validation: Cognito RS256 (not HS256). Pull JWKS from `https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json`. Validate `iss`, `aud`, expiry. Decode to `user_id`, `email`, `role`.

RBAC: 4 roles — `Viewer`, `Analyst`, `TreasuryManager`, `CFO`. `require_role(["TreasuryManager", "CFO"])` as a FastAPI dependency.

SQS publisher (`sqs/publisher.py`):
```python
import json
import boto3
from core_cash_shared.schemas.jobs import JobEnvelope

_client = boto3.client("sqs", region_name=settings.AWS_REGION)

def publish_job(envelope: JobEnvelope) -> str:
    """Publish job to SQS. Returns MessageId."""
    response = _client.send_message(
        QueueUrl=settings.SQS_QUEUE_URL,
        MessageBody=envelope.model_dump_json(),
        MessageGroupId=envelope.client_id,   # only if FIFO; omit for Standard
    )
    return response["MessageId"]
```

MongoDB client (`mongo/client.py`):
```python
from motor.motor_asyncio import AsyncIOMotorClient

_client: AsyncIOMotorClient | None = None

async def get_db():
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGODB_URI)
    return _client[settings.MONGODB_DB_NAME]
```

**`.env.example`**:
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/corecash
MONGODB_URI=mongodb+srv://...
MONGODB_DB_NAME=core_cash
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789/core-cash-jobs
AWS_REGION=us-east-1
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_xxxxxxxxx
COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-placeholder  # wired in S15 only
```

**Stop-and-review checklist**:
- [ ] `GET /health` returns `{"status": "ok", "service": "app-backend"}`
- [ ] JWT validation rejects expired/invalid tokens with `AUTH_TOKEN_INVALID`
- [ ] `get_current_user` dependency works end-to-end with a test Cognito token
- [ ] SQLAlchemy async session factory connects to PostgreSQL without error
- [ ] MongoDB Motor client connects to Atlas without error
- [ ] SQS publisher can send a test `JobEnvelope` without error (use localstack for local dev)
- [ ] `core-cash-shared` successfully imported

---

## S2: AI Backend Scaffold + SQS Consumer + LangGraph Skeleton

**Status**: ✅ Build-ready.

**Repo**: `core-cash-ai/`

**What to build**:

```
core-cash-ai/
├── pyproject.toml           # depends on core-cash-shared
├── .env.example
├── app/
│   ├── main.py              # FastAPI app (minimal — few routes; worker is main process)
│   ├── config.py
│   ├── database.py          # Read-only SQLAlchemy engine (same DSN, SELECT-only user)
│   ├── mongo/
│   │   └── client.py        # Motor client — AI Backend reads AND writes MongoDB
│   ├── sqs/
│   │   └── consumer.py      # SQS long-poll consumer loop
│   ├── worker/
│   │   ├── dispatcher.py    # Routes job_type → agent runner
│   │   └── runner.py        # run_agent_job(envelope) — top-level orchestrator
│   ├── graph/
│   │   ├── state.py         # LangGraph AgentState TypedDict
│   │   └── pipeline.py      # StateGraph definition — all 8 nodes wired
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py          # BaseAgent abstract class
│   │   └── .gitkeep         # Individual agents added in S3–S14
│   └── routes/
│       └── health.py        # GET /health (AI Backend)
```

**SQS Consumer** (`sqs/consumer.py`) — long-poll loop, runs as a background task on startup:
```python
import asyncio
import json
import boto3
from app.config import settings
from app.worker.dispatcher import dispatch
from core_cash_shared.schemas.jobs import JobEnvelope

async def start_consumer():
    sqs = boto3.client("sqs", region_name=settings.AWS_REGION)
    while True:
        response = sqs.receive_message(
            QueueUrl=settings.SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,       # long-poll
            VisibilityTimeout=300,    # 5 minutes; must complete job within this window
        )
        messages = response.get("Messages", [])
        for msg in messages:
            try:
                envelope = JobEnvelope.model_validate_json(msg["Body"])
                await dispatch(envelope)
                sqs.delete_message(
                    QueueUrl=settings.SQS_QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
            except Exception as e:
                # Do NOT delete — let visibility timeout expire → DLQ after 3 retries
                logger.error(f"Job processing failed: {e}")
        await asyncio.sleep(0)  # yield to event loop
```

**LangGraph State** (`graph/state.py`):
```python
from typing import TypedDict, Optional, Any, Dict
from datetime import datetime

class AgentState(TypedDict):
    job_id: str
    client_id: str
    user_id: str
    requested_at: datetime
    # Agent outputs — populated as pipeline progresses
    cash_position: Optional[Dict[str, Any]]
    liquidity_risk: Optional[Dict[str, Any]]
    forecast: Optional[Dict[str, Any]]
    action_recommendations: Optional[Dict[str, Any]]
    variance_explanation: Optional[Dict[str, Any]]
    treasury_continuity: Optional[Dict[str, Any]]
    cfo_summary: Optional[Dict[str, Any]]
    # Errors per agent — pipeline continues unless a hard dependency fails
    errors: Dict[str, str]
```

**LangGraph Pipeline** (`graph/pipeline.py`) — wire all 8 nodes even though most are stubs in S2:
```python
from langgraph.graph import StateGraph, END
from app.graph.state import AgentState

def build_pipeline() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("agent_1_cash_position",    run_agent_1)
    g.add_node("agent_3_liquidity_risk",   run_agent_3)
    g.add_node("agent_2_forecast",         run_agent_2)
    g.add_node("agent_4_recommendations",  run_agent_4)
    g.add_node("agent_5_variance",         run_agent_5)
    g.add_node("agent_7_continuity",       run_agent_7)
    g.add_node("agent_6_cfo_summary",      run_agent_6)
    g.add_node("agent_8_policy_control",   run_agent_8)

    g.set_entry_point("agent_1_cash_position")
    # Sequential MVP order:
    g.add_edge("agent_1_cash_position",   "agent_3_liquidity_risk")
    g.add_edge("agent_1_cash_position",   "agent_2_forecast")
    g.add_edge("agent_3_liquidity_risk",  "agent_4_recommendations")
    g.add_edge("agent_2_forecast",        "agent_4_recommendations")
    g.add_edge("agent_4_recommendations", "agent_8_policy_control")
    g.add_edge("agent_8_policy_control",  "agent_5_variance")
    g.add_edge("agent_5_variance",        "agent_7_continuity")
    g.add_edge("agent_7_continuity",      "agent_6_cfo_summary")
    g.add_edge("agent_6_cfo_summary",     END)

    return g.compile()
```

All 8 node functions are stubs in S2 — each returns a state with a TODO marker. Replace stubs with real implementations in S3–S14.

**MongoDB collections** (create indexes in S2):
```
agent_runs          — one document per agent pipeline run
recommendations     — Agent 4 output; Agent 7 reads from here
cfo_reports         — Agent 6 report output
daily_briefings     — Agent 6 briefing output
variance_reports    — Agent 5 output
job_status          — job_id → status, updated by worker
```

**Stop-and-review checklist**:
- [ ] `GET /health` on AI Backend returns `{"status": "ok", "service": "ai-backend"}`
- [ ] SQS consumer starts on app startup (`@app.on_event("startup")`)
- [ ] Consumer correctly deserialises `JobEnvelope` from SQS message body
- [ ] Failed job does NOT delete message (visibility timeout expiry → DLQ)
- [ ] LangGraph graph compiles without error (all 8 nodes wired even as stubs)
- [ ] MongoDB collections created with indexes: `job_id`, `client_id`, `created_at`
- [ ] PostgreSQL connection uses **read-only** DSN (SELECT-only IAM role)
- [ ] AI Backend cannot execute INSERT/UPDATE/DELETE against PostgreSQL (verify by attempting — must fail)

---

## S3: DB Migrations + Agent 1 (Daily Cash Position) + Accounts Endpoints

**Status**: ✅ Build-ready.

**What to build** (App Backend + AI Backend):

App Backend:
- `alembic/` migration set (run against PostgreSQL)
- `app/routes/accounts.py` — Accounts CRUD
- `app/routes/cash_position.py` — polling endpoint
- `app/routes/jobs.py` — generic `GET /jobs/{request_id}` status endpoint

AI Backend:
- `app/agents/daily_cash_position.py` — Agent 1 implementation
- `app/agents/daily_cash_position.py` registered in LangGraph pipeline (replaces stub)

**DB Migrations** — run in order:

```sql
-- Migration 001: Add available_balance to statement
ALTER TABLE statement
  ADD COLUMN available_balance NUMERIC(15,2);

-- Migration 002: Add OD + refresh + cash_position flag to account
ALTER TABLE account
  ADD COLUMN od_limit             NUMERIC(15,2) DEFAULT NULL,
  ADD COLUMN od_utilised_amount   NUMERIC(15,2) DEFAULT NULL,
  ADD COLUMN refresh_frequency    VARCHAR(20) NOT NULL DEFAULT 'Daily',
  ADD COLUMN include_in_cash_position BOOLEAN NOT NULL DEFAULT TRUE;
-- NOTE: od_headroom is NOT stored — computed by Agent 1 as (od_limit - od_utilised_amount)

-- Migration 003: FX rates
CREATE TABLE fx_rates (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id     UUID NOT NULL REFERENCES client(id),
  currency_from VARCHAR(3) NOT NULL,
  currency_to   VARCHAR(3) NOT NULL DEFAULT 'USD',
  rate          NUMERIC(18,6) NOT NULL,
  rate_date     DATE NOT NULL,
  entered_by    UUID NOT NULL REFERENCES users(id),
  entered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, currency_from, rate_date)
);

-- Migration 004: Manual assumptions confidence field
ALTER TABLE manual_assumptions
  ADD COLUMN confidence_pct NUMERIC(5,2);
-- After backfill: DROP COLUMN confidence (old enum column)

-- Migration 005: System config
CREATE TABLE system_config (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id   UUID NOT NULL REFERENCES client(id),
  config_key  VARCHAR(100) NOT NULL,
  config_val  TEXT NOT NULL,
  updated_by  UUID REFERENCES users(id),
  updated_at  TIMESTAMPTZ DEFAULT now(),
  UNIQUE (client_id, config_key)
);
-- Seed defaults:
-- ('forecast_confidence_threshold', '50')
-- ('warning_threshold_pct', '70')
-- ('significant_outflow_pct', '10')

-- Migration 006: Job status table (App Backend polls this)
CREATE TABLE job_status (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id     UUID NOT NULL REFERENCES client(id),
  job_id        UUID NOT NULL UNIQUE,
  job_type      VARCHAR(50) NOT NULL,
  status        VARCHAR(20) NOT NULL DEFAULT 'queued',
  requested_by  UUID REFERENCES users(id),
  requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at  TIMESTAMPTZ,
  result_id     TEXT,   -- MongoDB _id of the result document
  error_message TEXT
);
CREATE INDEX idx_job_status_job_id ON job_status(job_id);
CREATE INDEX idx_job_status_client_id ON job_status(client_id);

-- Migration 007: Mock data — set available_balance
UPDATE statement
  SET available_balance = closing_balance
  WHERE available_balance IS NULL;

-- Migration 008: Mock OD test data
UPDATE account
  SET od_limit = 500000
  WHERE account_name = 'BofA EUR Reserve';
```

**Agent 1: Daily Cash Position** (AI Backend, `app/agents/daily_cash_position.py`):

Key implementation rules:

```python
# 1. ONLY include accounts where include_in_cash_position = TRUE in usable cash totals
accounts = db.execute(
    "SELECT ... FROM account WHERE client_id = :cid AND include_in_cash_position = TRUE"
)

# 2. Cash position definitions — order matters
total_cash_usd     = sum(acct.closing_balance * fx_rate for acct in accounts)
available_cash_usd = sum(acct.available_balance * fx_rate for acct in accounts)
restricted_cash_usd = sum(
    acct.available_balance * fx_rate
    for acct in accounts if acct.restricted_flag
)
usable_cash_usd = available_cash_usd - restricted_cash_usd
od_limit_total_usd = sum(
    acct.od_limit * fx_rate
    for acct in accounts if acct.od_limit is not None
)
# NEVER: usable_cash_usd += od_limit_total_usd

# 3. od_headroom — computed here, never stored
def compute_od_headroom(od_limit, od_utilised_amount):
    if od_limit is None:
        return None
    return od_limit - (od_utilised_amount or 0)

# 4. Status logic — 70% threshold (not 80%)
def account_status(available_balance, min_threshold):
    if available_balance >= min_threshold:
        return "Green"
    elif available_balance >= min_threshold * 0.70:
        return "Yellow"
    else:
        return "Red"

# 5. FX rate sourcing
today_rate = db.get_fx_rate(currency, date=today)
if today_rate is None:
    prior_rate = db.get_fx_rate(currency, date=yesterday)
    fx_rates_warning = True
    rate = prior_rate
else:
    fx_rates_warning = False
    rate = today_rate

# 6. Confidence logic
def feed_confidence(refresh_frequency, hours_since_last_statement):
    if refresh_frequency == "Manual":
        return "High"   # Manual feeds not assessed for staleness
    if hours_since_last_statement < 24:
        return "High"
    elif hours_since_last_statement < 48:
        return "Medium"
    else:
        return "Low"
# Overall confidence = min(all feed confidences), where Low < Medium < High
```

**Async job pattern** (App Backend):

`POST /api/cash-position/request` → publishes `JobEnvelope(job_type="cash_position")` to SQS, inserts row into `job_status` (status=queued), returns:
```json
HTTP 202
{"request_id": "uuid", "status": "queued", "job_type": "cash_position"}
```

`GET /api/jobs/{request_id}` → reads `job_status` table, returns current status. When `status=completed`, includes `result_id` (MongoDB `_id`).

`GET /api/cash-position/{result_id}` → reads MongoDB `agent_runs` collection, returns Agent 1 output document.

**Accounts endpoints** (App Backend, synchronous):
```
GET  /api/accounts                       → list all accounts for client
GET  /api/accounts/{account_id}          → single account detail
POST /api/accounts                       → create account (TreasuryManager, CFO only)
PUT  /api/accounts/{account_id}          → update account
GET  /api/entities                       → list legal entities
```

**Mock fixtures** to add in `utils/fixtures.py`:
- 4 entities, 6 accounts (include 1 with `include_in_cash_position = FALSE` to test exclusion)
- 30+ days of statements with `available_balance` set
- 1 account with `od_limit = 500000` and `closing_balance = -50000` to test OD headroom display
- 1 FX rate record for today (GBP/USD = 1.27)
- 3 manual_assumption records with `confidence_pct`: 75, 45, 60

**Stop-and-review checklist**:
- [ ] All 8 migrations run cleanly on a fresh schema
- [ ] `od_headroom` is NOT in any DB column — computed only
- [ ] `usable_cash_usd` excludes OD headroom — verified by unit test
- [ ] `usable_cash_usd` excludes accounts where `include_in_cash_position = FALSE`
- [ ] Status uses 70% threshold — verified by unit test
- [ ] FX rate fallback: yesterday's rate used + `fx_rates_warning = true`
- [ ] `POST /api/cash-position/request` returns 202 with `request_id`
- [ ] `GET /api/jobs/{request_id}` returns `queued` → `processing` → `completed`
- [ ] `GET /api/cash-position/{result_id}` returns Agent 1 output matching `api-contract-v3.md`
- [ ] AI Backend writes Agent 1 output to MongoDB `agent_runs` collection
- [ ] AI Backend updates `job_status` table to `completed` after write
- [ ] Response shape matches `api-contract-v3.md` Section: Cash Position

---

## S4: Agent 3 — Liquidity Risk

**Status**: ✅ Build-ready (depends on S3).

**What to build** (AI Backend):
- `app/agents/liquidity_risk.py` — Agent 3 implementation
- Register in LangGraph pipeline (replaces stub)

**App Backend** — add polling endpoints:
- `POST /api/liquidity-risk/request`
- `GET /api/liquidity-risk/{result_id}`

**Key implementation rules**:

```python
# Risk score — revised weights from v2.0
base = 1
breach_pts = min(len(active_breaches) * 2, 6)   # +2 per breach, cap at 6
stale_pts  = 1 if any(feed.hours_stale > 48 for feed in feeds) else 0
ar_conc_pts = 1 if ar_concentration_pct > 70 else 0
# shortfall_pts = +2 if any forecast day has usable_cash < min_threshold
# Wire shortfall_pts in S14 when Agent 2 is unblocked; use 0 for now with TODO
shortfall_pts = 0  # TODO: wire when Agent 2 available
raw = base + breach_pts + stale_pts + ar_conc_pts + shortfall_pts
score = min(raw, 10)

risk_level = (
    "Low"    if score <= 3 else
    "Medium" if score <= 6 else
    "High"
)

# AR Concentration — AR only, not cash or AP
# Label: ar_concentration_risk (not concentration_risk)
total_ar = sum(item.expected_amount for item in ar_schedule)
by_counterparty = group_by_counterparty(ar_schedule)
top_3 = sorted(by_counterparty.items(), key=lambda x: x[1], reverse=True)[:3]
top_3_total = sum(amt for _, amt in top_3)
concentration_pct = (top_3_total / total_ar * 100) if total_ar > 0 else 0
breached = concentration_pct > 70

# Narrative — LLM mock for S4
narrative = (
    f"Liquidity risk is {risk_level}. "
    f"{len(active_breaches)} active breach(es). "
    f"AR concentration at {concentration_pct:.1f}% (threshold: 70%). "
    f"{'One or more stale feeds.' if stale_pts else 'All feeds current.'}"
)
# Replace this template with real Claude API call in S15
```

**Stop-and-review checklist**:
- [ ] Breach score: +2 per breach, capped at 6
- [ ] Score capped at 10 total
- [ ] AR concentration uses AR schedule only (not AP, not cash)
- [ ] Label in output is `ar_concentration_risk`
- [ ] `shortfall_pts = 0` with TODO comment for S14 wiring
- [ ] Response matches `api-contract-v3.md` Section: Liquidity Risk
- [ ] Active breaches column order: entity → account → threshold → balance → shortfall → currency
- [ ] Unit test: breach + stale produces correct score

---

## S5: CSV Parsers — Bank Balances, AR Data, AP Data

**Status**: ✅ Build-ready.

**What to build** (App Backend):
- `app/parsers/csv_bank_balances.py`
- `app/parsers/csv_ar.py`
- `app/parsers/csv_ap.py`
- `app/routes/uploads.py`

**Endpoints**:
```
POST /api/uploads/bank-balances    → CSV → Statement records
POST /api/uploads/ar-data          → CSV → ar_schedule records
POST /api/uploads/ap-data          → CSV → ap_schedule records + triggers forecast re-queue
GET  /api/uploads/history          → list of past uploads (source_file table)
```

**Parser rules**:

```python
# Bank balance CSV: flexible column mapping
BANK_BALANCE_COLUMN_MAP = {
    "account_name":       ["Account Name", "Account", "Acct Name"],
    "closing_balance":    ["Closing Balance", "Balance", "Closing"],
    "available_balance":  ["Available Balance", "Available", "Avail"],
    "currency":           ["Currency", "CCY", "Ccy"],
    "statement_date":     ["Statement Date", "Date", "Value Date"],
    "bank_name":          ["Bank", "Bank Name"],
}

# Validation rules — reject file with error if violated:
# - closing_balance must be numeric (negative values allowed for OD)
# - statement_date must be parseable as a date
# - currency must be 3-char ISO
# - account_name must match an existing account.account_name for this client
# - Duplicate account + date combination: update, do not duplicate

# On success: insert/update Statement record, update source_file record
# On partial failure: return 207 with per-row success/error list
```

```python
# AP upload must trigger forecast re-queue
async def handle_ap_upload(file, client_id, user_id, db, sqs):
    rows_ok, errors = parse_ap_csv(file)
    if rows_ok:
        save_to_ap_schedule(rows_ok, db)
        # Trigger forecast re-run
        envelope = JobEnvelope(
            job_type=JobType.CASH_POSITION,  # forecast triggered separately
            client_id=client_id,
            user_id=user_id,
            payload={"trigger": "ap_upload"},
        )
        publish_job(envelope)
    return {"uploaded": len(rows_ok), "errors": errors}
```

**File constraints** (enforce in route before parsing):
- Max file size: 10 MB
- Accepted content types: `text/csv`, `application/vnd.ms-excel`
- Excel (`.xlsx`) is **excluded from MVP** — return `VALIDATION_UNSUPPORTED_FORMAT` if received

**Stop-and-review checklist**:
- [ ] Bank balance CSV parser handles flexible column names
- [ ] Negative closing_balance accepted (OD accounts)
- [ ] Duplicate account+date → UPDATE (not INSERT second row)
- [ ] AP upload triggers SQS job publish after save
- [ ] AR upload does NOT trigger forecast re-queue
- [ ] Excel upload returns 400 `VALIDATION_UNSUPPORTED_FORMAT`
- [ ] File > 10MB returns 413 `VALIDATION_FILE_TOO_LARGE`
- [ ] `GET /api/uploads/history` returns source_file rows for this client
- [ ] Partial failure returns 207 with per-row error detail

---

## S6: Agent 4 (Action Recommendation, Mocked) + Agent 8 (Policy Control)

**Status**: ✅ Build-ready (depends on S3, S4).

**What to build** (AI Backend):
- `app/agents/action_recommendation.py` — Agent 4 (mocked LLM)
- `app/agents/policy_control.py` — Agent 8 (deterministic)
- Both registered in LangGraph pipeline

**App Backend** — add:
- `POST /api/recommendations/request`
- `GET /api/recommendations/{result_id}`
- `POST /api/recommendations/{recommendation_id}/approve`
- `POST /api/recommendations/{recommendation_id}/reject`

**Agent 4 — mocked LLM output**:

```python
# LLM MOCK — S6 through S14. Real API in S15.
# Replace this function with Anthropic client call in S15.
def generate_recommendation_text(context: dict) -> dict:
    breach = context.get("breach")
    surplus = context.get("surplus")
    if breach:
        return {
            "why": (
                f"{breach['entity_name']} {breach['currency']} balance is "
                f"{breach['currency']} {breach['shortfall']:,} below the "
                f"{breach['currency']} {breach['min_threshold']:,} minimum threshold."
            ),
            "what": (
                f"Evaluate funding of {breach['currency']} {breach['shortfall'] * 1.2:,.0f} "
                f"to {breach['account_name']} from available surplus pool, "
                f"subject to Finance Director approval per DOA policy."
            ),
            "when": "Today before treasury close. Delay beyond cut-off means next business day settlement.",
            "control": {
                "approval_owner": "Finance Director (per DOA policy)",
                "policy_check": "Pass",
                "human_approval_required": True,
            },
        }
    # Add surplus/investment template similarly
    raise NotImplementedError("Only breach template implemented in mock")
```

**Agent 8 — Policy Control (deterministic — no mock needed)**:

```python
def validate_recommendation(rec: dict, accounts: list, investment_policy_uploaded: bool) -> tuple[bool, str | None]:
    # Check 1: All 4 fields present
    for field in ["why", "what", "when", "control"]:
        if not rec.get(field):
            return False, f"Missing required field: {field}"

    # Check 2: Evaluative language in 'what'
    execution_verbs = ["Transfer", "Execute", "Send", "Move", "Initiate", "Pay"]
    for verb in execution_verbs:
        if verb.lower() in rec["what"].lower():
            # Rewrite rather than block — Agent 8 rewrites execution verbs
            rec["what"] = rec["what"].replace(verb, "Evaluate")

    # Check 3: Investment rec without policy
    if rec.get("type") == "Investment" and not investment_policy_uploaded:
        # Downgrade to surplus-flag-only
        rec["what"] = rec["what"].replace(
            "investment of surplus",
            "surplus identified — no investment SOP uploaded; review company policy before acting"
        )

    # Check 4: human_approval_required must be True
    if not rec.get("control", {}).get("human_approval_required"):
        return False, "human_approval_required must be True"

    return True, None
```

**Approval endpoints** (App Backend, PostgreSQL):

`POST /api/recommendations/{recommendation_id}/approve`:
- RBAC: TreasuryManager, CFO only
- Updates MongoDB `recommendations` document: `approval_status = "Approved"`, `approved_by`, `approved_at`
- No autonomous action is taken — approval is a record only

**Recommendation cap enforcement**:
```python
recommendations = sorted(recommendations, key=lambda r: r["priority"])[:10]
```

**Stop-and-review checklist**:
- [ ] All recommendations have non-null Why, What, When, Control fields
- [ ] `what` field uses only Evaluate/Consider/Review/Propose/Escalate
- [ ] Agent 8 rewrites execution verbs (Transfer → Evaluate) rather than silently dropping
- [ ] Investment recommendation without uploaded SOP → downgraded to surplus-flag-only
- [ ] `human_approval_required: true` on every recommendation
- [ ] Maximum 10 items in response
- [ ] All start as `approval_status: Pending`
- [ ] Approve/reject endpoints require TreasuryManager or CFO role
- [ ] No autonomous action occurs on approval — approval is a record only
- [ ] LLM mock returns structurally valid output matching agent-specifications-v2.md shape
- [ ] Response matches `api-contract-v3.md` recommendations section

---

## ⚠️ S7: Forecast Scaffold — BLOCKED

**Status**: ⛔ DO NOT implement forecast calculation until opening balance rule confirmed by Paul + amit j.

**What is blocked**: Agent 2 cannot be built until this is resolved:

> **At what point does Opening Cash anchor?**
> - Option A: Prior-day end-of-day closing balance from the most recently ingested bank statement
> - Option B: [TBD]

**Safe pre-work to do in S7** (will not be invalidated by the decision):
- `app/agents/forecast_intelligence.py` — scaffold file with stub node returning 503 state
- ORM query helpers: AR schedule by entity/date range, AP schedule by entity/date range
- `manual_assumptions` filter: `confidence_pct >= 50` (read threshold from `system_config`)
- Forecast re-trigger logic skeleton (on AP upload, on assumption change)
- Significant outflow flag logic: `outflow > usable_cash * significant_outflow_pct`
- Entity-level aggregation skeleton in base currency

**What to return from `/api/forecast/request`** until unblocked:
```json
HTTP 503
{
  "error": {
    "code": "OPENING_BALANCE_UNRESOLVED",
    "message": "Forecast unavailable. Opening balance alignment logic is under review.",
    "severity": "error"
  }
}
```

**Action required before S14**: Paul + amit j confirm opening balance rule → update `financial-business-logic-v2.md` Section 2.2 → update this document S14 → proceed.

---

## S8: Config / FX Endpoints

**Status**: ✅ Build-ready.

**What to build** (App Backend):
- `app/routes/config.py`

**Endpoints**:
```
GET  /api/config/fx-rates                    → list FX rates for client (today + history)
POST /api/config/fx-rates                    → enter FX rate (Analyst, TM, CFO)
GET  /api/config/investment-policy           → current active investment policy doc
POST /api/config/investment-policy           → upload new policy (TM, CFO only)
GET  /api/config/investment-cutoffs          → list cutoffs per entity
PUT  /api/config/investment-cutoffs/{entity} → update cutoff (TM, CFO only)
GET  /api/config/system                      → list system_config key/val for client
PUT  /api/config/system/{key}                → update system_config (CFO only)
GET  /api/metadata/entities                  → list legal entities
GET  /api/metadata/currencies                → list currencies with accounts
```

**FX rate entry rules**:
- One rate per `currency_from` per date per client
- Duplicate insert → update (not error)
- `currency_to` always `USD` for MVP
- No FX rate for today → fallback to prior day's rate; warn via `fx_rates_warning`

**Investment policy upload**:
- Store PDF URL (S3 presigned or stored path)
- Mark prior active policy as `is_active = false` on new upload
- `investment_policy` null check used by Agent 8 in S6

**Stop-and-review checklist**:
- [ ] FX rate duplicate → update, not 409
- [ ] Investment policy upload deactivates prior active policy
- [ ] `PUT /api/config/system/{key}` restricted to CFO role
- [ ] Investment cutoff includes timezone field (never assume EST)
- [ ] Response shapes match `api-contract-v3.md` config section

---

## S9: Agents 6 (CFO Summary, Mocked) + 7 (Treasury Continuity)

**Status**: ✅ Build-ready (depends on S3–S6).

**What to build** (AI Backend):
- `app/agents/cfo_summary.py` — Agent 6 (mocked)
- `app/agents/treasury_continuity.py` — Agent 7 (deterministic)
- Both registered in LangGraph pipeline

**App Backend**:
- `POST /api/cfo-summary/request`
- `GET /api/cfo-summary/{result_id}`
- `GET /api/cfo-summary/{result_id}/export` (PDF export — return 501 stub in S9; implement in later session)
- `POST /api/daily-briefing/request`
- `GET /api/daily-briefing/{result_id}`
- `GET /api/cfo-summary/live-insights` (synchronous polling; App Backend reads latest from MongoDB)

**Agent 6 — MTD Change rule (not YTD)**:
```python
# Cash Position section
mtd_change_usd = current_balance_usd - balance_on_first_of_month_usd
trend = "Up" if mtd_change_usd > 0 else ("Down" if mtd_change_usd < 0 else "Flat")
```

**Agent 6 — OD headroom in CFO Summary**:
```python
# OD headroom must be shown separately — never merged with usable cash
# Source from Agent 1 output; do not recalculate
od_headroom = agent_1_output["entities"][i]["accounts"][j]["od_headroom"]
```

**Agent 6 — Daily Briefing rules**:
- Output is **prose only** — no structured metrics objects in briefing response
- "Behind Us" (last 4 days): date + narrative sentence + optional precedent callout from Agent 7
- "Ahead of Us" (next 4 days): date + narrative sentence + Major Outflow Alert if outflow > 10% of usable_cash
- Major Outflow Alert text: `"⚠️ Major outflow of {currency} {amount:,} ({pct:.1f}% of usable cash) expected — flag for Finance Director review."`

**Agent 6 — LLM mock**:
```python
# MOCK — S9. Replace with Anthropic client call in S15.
def generate_cfo_report_narrative(context: dict) -> str:
    total = context["usable_cash_usd"]
    risk = context["risk_level"]
    return (
        f"[MOCK CFO SUMMARY] Usable cash stands at USD {total:,.0f}. "
        f"Liquidity risk is {risk}. "
        f"{len(context['active_recommendations'])} recommendation(s) pending approval. "
        f"[Replace with Claude API call in S15]"
    )
```

**Agent 7 — Treasury Continuity** (deterministic, no LLM mock needed):
```python
# Agent 7 reads MongoDB recommendations collection only (not decision_log — deferred Phase 2)
# Match current context to historical recommendations by: entity, breach type, currency
def find_precedents(current_breaches: list, client_id: str, mongo_db) -> list:
    precedents = []
    for breach in current_breaches:
        past = mongo_db["recommendations"].find({
            "client_id": client_id,
            "type": "Funding",
            "entity_id": breach["entity_id"],
            "approval_status": "Approved",
        }).sort("created_at", -1).limit(3)
        for p in past:
            precedents.append({
                "date": p["created_at"].date().isoformat(),
                "situation": p.get("why", ""),
                "action_taken": p.get("what", ""),
                "outcome": p.get("outcome_note", "No outcome recorded"),
                "relevance": f"Current {breach['entity_name']} breach matches this pattern.",
            })
    return precedents
```

**Stop-and-review checklist**:
- [ ] CFO Summary cash position uses `mtd_change_usd` — not `ytd_change_usd`
- [ ] OD headroom displayed separately from usable cash in CFO Summary
- [ ] Daily Briefing output is prose — no structured objects in response body
- [ ] Major Outflow Alert fires at >10% of usable_cash in next 4 days
- [ ] Agent 7 reads from MongoDB `recommendations` collection only (not PostgreSQL decision_log)
- [ ] `GET /api/cfo-summary/live-insights` returns synchronously from MongoDB latest
- [ ] Briefing precedent callout included when Agent 7 returns matches
- [ ] Response shapes match `api-contract-v3.md`

---

## S10: Agent 5 — Variance Explanation (Mocked)

**Status**: ✅ Build-ready (depends on S3). Partially blocked by Agent 2, but arithmetic can be tested against mock forecast data.

**What to build** (AI Backend):
- `app/agents/variance_explanation.py` — Agent 5 (mocked LLM narrative)
- Registered in LangGraph pipeline

**App Backend**:
- `POST /api/forecast/variance/request`
- `GET /api/forecast/variance/{variance_id}`
- `GET /api/forecast/variance/current` (returns latest variance report from MongoDB)

**Key implementation rules**:

```python
# Variance arithmetic
total_variance = actual_closing - forecast_closing
variance_pct   = (actual_closing - forecast_closing) / abs(forecast_closing) * 100
variance_direction = "Favorable" if total_variance > 0 else "Unfavorable"

# Forecast accuracy — tolerance is ±5% (not ±3%)
accuracy_days = sum(
    1 for d in daily_pairs
    if abs(d.actual - d.forecast) < abs(d.forecast) * 0.05
)
forecast_accuracy_pct = accuracy_days / len(daily_pairs) * 100 if daily_pairs else 0

# Driver attribution
attributed_total = sum(d["amount_usd"] for d in drivers)
unexplained = total_variance - attributed_total

# NEVER FORCE TO ZERO:
if abs(unexplained) > 0.01:   # float noise threshold
    response["unexplained_variance_usd"] = round(unexplained, 2)
    response["unexplained_variance_note"] = (
        "Remaining variance could not be attributed to available data. "
        "Manual investigation recommended."
    )
else:
    response["unexplained_variance_usd"] = 0
    response["unexplained_variance_note"] = None

# One-off flag (Rule B): outflow > 3× 30-day average
thirty_day_avg = sum(daily_outflows[-30:]) / max(len(daily_outflows[-30:]), 1)
for driver in drivers:
    driver["one_off_flag"] = abs(driver["amount_usd"]) > 3 * thirty_day_avg
    driver["one_off_basis"] = (
        f"Exceeds 3× 30-day average daily outflow (USD {thirty_day_avg:,.0f})"
        if driver["one_off_flag"] else None
    )
```

**Stop-and-review checklist**:
- [ ] `unexplained_variance_usd` always present in response (0 if fully attributed, non-zero if residual)
- [ ] Drivers never forced to sum to total — residual always surfaced
- [ ] `one_off_flag` and `one_off_basis` present on every driver object
- [ ] Forecast accuracy uses ±5% tolerance
- [ ] Variance % formula matches: `(actual - forecast) / |forecast| × 100`
- [ ] Unit test: partially attributed variance shows correct `unexplained_variance_usd`
- [ ] Response matches `api-contract-v3.md` variance section

---

## S11: Audit Log + Approvals Workflow

**Status**: ✅ Build-ready.

**What to build** (App Backend):
- `app/models/audit_log.py` — SQLAlchemy model
- `app/routes/audit.py`
- `app/middleware/audit.py` — middleware that logs all mutating requests

**DB Migration** (add in S11):
```sql
CREATE TABLE audit_log (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id     UUID NOT NULL REFERENCES client(id),
  user_id       UUID REFERENCES users(id),
  action        VARCHAR(100) NOT NULL,
  entity_type   VARCHAR(50),
  entity_id     UUID,
  before_state  JSONB,
  after_state   JSONB,
  ip_address    INET,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_log_client_id ON audit_log(client_id);
CREATE INDEX idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at);
```

**Audit events to log** (minimum):
- `recommendation.approved` — user_id, recommendation_id, approved_at
- `recommendation.rejected` — user_id, recommendation_id
- `upload.bank_balances` — user_id, file_name, rows_imported
- `upload.ar_data` — user_id, file_name, rows_imported
- `upload.ap_data` — user_id, file_name, rows_imported
- `config.fx_rate_entered` — user_id, currency, rate, date
- `config.investment_policy_uploaded` — user_id

**Endpoints**:
```
GET /api/audit-log                         → paginated audit log (TM, CFO only)
GET /api/audit-log?entity_type=recommendation  → filter by entity
```

**Stop-and-review checklist**:
- [ ] Every approval/rejection recorded in audit_log
- [ ] Every upload recorded with row count
- [ ] Audit log readable by TreasuryManager and CFO only
- [ ] Audit log is append-only — no update/delete endpoints

---

## S12: Chat SSE Endpoint

**Status**: ✅ Build-ready (depends on S3–S10).

**What to build** (AI Backend):
- `app/routes/chat.py` — SSE streaming endpoint

**Endpoint**: `POST /ai/chat/stream` (AI Backend base URL, not App Backend)

```
POST https://ai.{customer}.core-cash.com/ai/chat/stream
Content-Type: application/json
Authorization: Bearer {jwt}

Request: {"message": "string", "session_id": "uuid"}
Response: text/event-stream

data: {"type": "token", "content": "The current"}
data: {"type": "token", "content": " usable cash"}
data: {"type": "done", "session_id": "uuid"}
```

**Chat scope rules** (enforced by the chat handler):

```python
SCOPE_MAP = {
    # Keywords → which MongoDB collection to query
    "balance|cash|position":          "agent_runs",         # Agent 1
    "risk|breach|stale|concentration": "agent_runs",        # Agent 3
    "recommendation|action|surplus":   "recommendations",   # Agent 4
    "summary|briefing|cfo|report":     "cfo_reports",       # Agent 6
    "forecast|projection|outlook":     "agent_runs",        # Agent 2 (when available)
    "variance|explain|why":            "variance_reports",  # Agent 5
}

# Chat agent only reads from MongoDB — never from PostgreSQL raw tables
# Never reads raw uploaded files
# Answers are derived from the latest completed agent output for this client
```

**SSE implementation** (FastAPI):
```python
from fastapi.responses import StreamingResponse
from fastapi import Request

@router.post("/ai/chat/stream")
async def chat_stream(request: Request, body: ChatRequest, current_user = Depends(get_current_user)):
    async def event_generator():
        # 1. Query relevant MongoDB collection based on message scope
        context = await get_chat_context(body.message, current_user.client_id)
        # 2. In S12, stream a mocked response token by token
        # Replace with Anthropic streaming API in S15
        mock_response = f"[MOCK] Based on the latest data: {context.get('summary', 'No data available.')}"
        for word in mock_response.split():
            yield f"data: {json.dumps({'type': 'token', 'content': word + ' '})}\n\n"
            await asyncio.sleep(0.05)
        yield f"data: {json.dumps({'type': 'done', 'session_id': str(body.session_id)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**Stop-and-review checklist**:
- [ ] SSE endpoint is on AI Backend base URL (not App Backend)
- [ ] JWT validated on AI Backend
- [ ] Chat reads from MongoDB only — no raw PostgreSQL table access
- [ ] `data:` prefixed lines with `\n\n` terminator (SSE spec)
- [ ] `{"type": "done"}` event sent as final message
- [ ] Mock response is structurally valid SSE

---

## S13: BAI2 / camt.053 / MT940 Parsers

**Status**: ✅ Build-ready.

**What to build** (App Backend):
- `app/parsers/bai2.py`
- `app/parsers/camt053.py`
- `app/parsers/mt940.py`
- Hook into `POST /api/uploads/bank-balances` (detect format, route to correct parser)

**Format detection**:
```python
def detect_format(file_content: bytes, filename: str) -> str:
    if filename.endswith(".csv"):
        return "csv"
    first_line = file_content.decode("utf-8", errors="ignore").split("\n")[0]
    if first_line.startswith("01,"):
        return "bai2"
    if "<Document" in first_line or "camt.053" in file_content.decode("utf-8", errors="ignore")[:500]:
        return "camt053"
    if first_line.startswith(":20:") or ":60F:" in first_line:
        return "mt940"
    raise ValueError("Unsupported file format")
```

**BAI2 parser**: Extract Group Header (01), Account Identifier (03), Transaction Detail (16), Account Trailer (49), Group Trailer (99). Map `closing_ledger` to `closing_balance`, `available_balance` where present.

**camt.053 parser**: XML namespace-aware parse (`urn:iso:std:iso:20022:tech:xsd:camt.053.001.02` or `.08`). Extract `Bal/Amt` where `Cd = CLBD` (closing booked) and `Cd = AVBL` (available).

**MT940 parser**: Parse `:60F:` (opening balance), `:62F:` / `:62M:` (closing balance), `:64:` (available). Note: MT940 sign convention — `D` prefix = debit (negative).

**All parsers produce the same internal dict**:
```python
{
    "account_identifier": str,   # match to account.bank_account_number
    "currency": str,
    "statement_date": date,
    "closing_balance": Decimal,
    "available_balance": Decimal | None,
}
```

**Stop-and-review checklist**:
- [ ] Format auto-detected from content (not filename alone)
- [ ] All 3 parsers produce same internal dict shape
- [ ] MT940 `D` prefix correctly handled as negative
- [ ] camt.053 namespace-aware (not brittle to namespace version)
- [ ] Parsed rows upserted into `statement` table (same logic as CSV parser)
- [ ] Unsupported format → 400 `VALIDATION_UNSUPPORTED_FORMAT`
- [ ] Excel → 400 (not silently rejected)

---

## S14: Forecast Unblock — Agent 2 Full Implementation

**Status**: ⛔ DO NOT START until Paul + amit j confirm opening balance rule.

**When unblocked**:
1. Update `financial-business-logic-v2.md` Section 2.2 with confirmed opening balance rule
2. Update this document S14 with the rule
3. Build `app/agents/forecast_intelligence.py` (AI Backend) — replace S7 stub
4. Wire `shortfall_pts` in Agent 3 (S4 TODO comment)
5. Wire Agent 5 variance against real forecast data (S10 used mock forecast)
6. Assumption confidence filter: read `forecast_confidence_threshold` from `system_config`
7. Pattern signals mode: separate output to `/ai/trends/predictions` — never merged with `/api/forecast/{result_id}`

**Forecast endpoints** (App Backend):
```
POST /api/forecast/request              → queue forecast job → 202
GET  /api/jobs/{request_id}             → poll status
GET  /api/forecast/{result_id}          → Agent 2 output
GET  /api/forecast/variance/current     → latest variance report
POST /api/forecast/variance/request     → queue variance explanation job → 202
GET  /api/forecast/variance/{result_id} → Agent 5 output
```

**Pattern signals** (separate endpoint, AI Backend):
```
GET /ai/trends/predictions              → Agent 2 pattern signals only
```
Pattern signals are architecturally separate from forecasts. These endpoints are on the AI Backend base URL, not App Backend. Never return pattern signals inside a `/api/forecast/{result_id}` response.

---

## S15: Real LLM Wiring — Agents 4, 5, 6 + Chat

**Status**: 🔒 Build only after Step 8 sign-off (all prior sessions reviewed and accepted).

**What to do**:

```python
# Wire Anthropic client — replace ALL mock template strings in:
# - app/agents/action_recommendation.py (Agent 4)
# - app/agents/variance_explanation.py  (Agent 5)
# - app/agents/cfo_summary.py           (Agent 6)
# - app/routes/chat.py                  (chat stream)

from anthropic import Anthropic

client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# Agent 4 example:
def generate_recommendation_text(context: dict) -> dict:
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": build_recommendation_prompt(context)
        }]
    )
    # Parse structured JSON from response.content[0].text
    return parse_recommendation_json(response.content[0].text)
```

**`.env` placeholder** (set in S1, wired in S15):
```
ANTHROPIC_API_KEY=sk-ant-placeholder   # Set real key here for S15
```

**Stop-and-review checklist**:
- [ ] All 4 mock template strings replaced with Anthropic client calls
- [ ] Agent 4 output still passes Agent 8 policy control validation after LLM wiring
- [ ] Evaluative language constraint still enforced (Agent 8 rewrites violations)
- [ ] Why/What/When/Control all populated by LLM — none null
- [ ] Chat SSE streams real Anthropic response tokens
- [ ] All existing tests still pass (LLM output conforms to schemas)
- [ ] No mock strings remain in production code paths

---

## Critical Rules — Never Violate

| Rule | Detail |
|---|---|
| **Evaluative language** | Recommendation `what` field: Evaluate / Consider / Review / Propose / Escalate only. Never: Transfer / Execute / Send / Move / Initiate / Pay. |
| **Why/What/When/Control** | All four fields mandatory on every recommendation. Agent 8 blocks violations. |
| **70% threshold** | Account Yellow status at ≥70% of min_threshold. Never 80%. |
| **Unexplained Variance** | Never force drivers to sum to total. Residual = Unexplained Variance, always surfaced. |
| **OD separate** | `od_headroom` never added to `usable_cash`. Always displayed separately. Never stored in DB. |
| **od_headroom computed** | `od_headroom = od_limit − od_utilised_amount`. Computed by Agent 1 at run time. Not stored. |
| **include_in_cash_position** | Accounts with `include_in_cash_position = FALSE` excluded from `usable_cash_usd` rollup. |
| **Assumption filter** | Only assumptions with `confidence_pct >= 50` used in forecast. Read threshold from `system_config`. |
| **Predictions ≠ Forecasts** | Pattern signals: `/ai/trends/predictions` only. Never in forecast response. |
| **No autonomous action** | No agent executes anything. Approvals are records only. `approval_status: Pending` until user acts. |
| **MTD not YTD** | CFO Summary cash position: MTD change. YTD removed from codebase. |
| **AR Concentration only** | Concentration risk on AR only. Label: `ar_concentration_risk`. |
| **Excel excluded** | CSV, BAI2, camt.053, MT940 only. Excel upload returns `VALIDATION_UNSUPPORTED_FORMAT`. |
| **LLM mock boundary** | Agents 4, 5, 6, Chat: mock strings in S0–S14. Real API in S15 only. |
| **AI Backend read-only PG** | AI Backend has SELECT-only PostgreSQL access. Enforce at IAM + DB level. |
| **No raw data in Chat** | Chat agent reads MongoDB agent outputs only. Never reads raw PostgreSQL tables or uploaded files. |
| **decision_log deferred** | MVP uses MongoDB recommendations for Agent 7. PostgreSQL decision_log table deferred to Phase 2. |

---

## Open Items — Do Not Build Around

| # | Item | Blocked Sessions | Rule |
|---|---|---|---|
| 1 | Opening balance anchor rule | S7, S14 (Agent 2) | Return 503 `OPENING_BALANCE_UNRESOLVED`; do not hardcode any assumption |
| 2 | Investment cut-off time values | S6 (investment recs) | Surplus-flag-only mode until amit j provides values |
| 3 | Investment policy document | S6 (investment recs) | Downgrade to surplus-flag-only if policy not uploaded |
| 4 | PDF parser | Upload endpoints | Accept CSV/BAI2/camt/MT940 only; return unsupported for PDF |

---

## Testing Requirements — Minimum Per Session

| Session | Required Tests |
|---|---|
| S0 | Import test: both services can import `core-cash-shared` without error |
| S1 | JWT validates correctly; SQS publisher sends message; MongoDB connects |
| S2 | SQS consumer deserialises `JobEnvelope`; LangGraph graph compiles; failed job does NOT delete from SQS |
| S3 | `usable_cash_usd` excludes OD; 70% status threshold; FX fallback to prior day; `od_headroom` computed not stored |
| S4 | Risk score calculation correct; score capped at 10; AR concentration label correct |
| S5 | CSV parser handles flexible columns; AP upload triggers SQS; Excel rejected |
| S6 | All 4 fields non-null on every recommendation; language evaluative; cap at 10; approval records correctly |
| S8 | FX duplicate → update; investment policy deactivates prior on upload |
| S9 | MTD change (not YTD); Daily Briefing is prose; OD headroom shown separately |
| S10 | `unexplained_variance_usd` never forced to zero; `one_off_flag` correct; ±5% tolerance |
| S11 | Approvals written to audit_log; audit_log append-only |
| S12 | SSE stream produces `data:` prefixed events; `done` event sent |
| S15 | Agent 8 still passes/rewrites LLM output; no mock strings remain |

---

## Success Criteria: S0–S15

**All sessions done when**:
- [ ] Both services run independently and communicate via SQS + MongoDB
- [ ] All agents produce output matching `agent-specifications-v2.md` exactly
- [ ] All endpoints return responses matching `api-contract-v3.md` exactly
- [ ] Full async job pattern works: POST → 202 → GET poll → GET result
- [ ] Pattern signals and forecasts are architecturally separate (different endpoints, never merged)
- [ ] Why/What/When/Control on all recommendations — verified by test
- [ ] No autonomous action — all recommendations `Pending` until user acts
- [ ] Unexplained Variance surfaced, never forced to zero — verified by test
- [ ] 70% threshold applied everywhere — verified by test
- [ ] OD headroom computed, not stored; never merged with usable cash — verified by test
- [ ] `include_in_cash_position = FALSE` accounts excluded from usable cash rollup
- [ ] Assumption confidence filter at 50% — verified by test
- [ ] MTD (not YTD) in CFO Summary — verified by test
- [ ] Excel upload rejected at upload endpoint
- [ ] AI Backend cannot write to PostgreSQL (verified by attempting INSERT — must fail)
- [ ] LLM mock in place for S0–S14; real API wired in S15