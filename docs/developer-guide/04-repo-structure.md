# Repository Structure

## Directory Tree

```
Core-Cash-Treasury-Backend/
│
├── shared/                              # Shared Python package (pip install -e ./shared)
│   ├── core_cash_shared/                # Source code
│   │   ├── __init__.py
│   │   ├── enums.py                     # Enum: JobType, JobStatus, ApprovalStatus, RiskLevel, etc.
│   │   ├── error_codes.py               # Constants: AUTH_*, VALIDATION_*, JOB_*, DATA_*, AGENT_*
│   │   └── schemas/                     # Pydantic models (reused by both services)
│   │       ├── __init__.py
│   │       ├── errors.py                # ErrorDetail, ErrorResponse
│   │       ├── jobs.py                  # JobEnvelope, JobStatus schema
│   │       ├── bank_statement.py        # Bank statement parsing
│   │       ├── chat.py                  # Chat message/event schemas
│   │       ├── forecast.py              # ForecastDayRow, ForecastResult (Session 13)
│   │       └── variance.py              # Variance explanation schemas
│   ├── setup.py                         # Package metadata
│   ├── pyproject.toml                   # Build config
│   └── MANIFEST.in
│
├── app-backend/                         # Primary user-facing service (port 8000)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                      # ⭐ Entry point: FastAPI app, lifespan, middleware, routers
│   │   ├── config.py                    # Environment variables (DATABASE_URL, MONGO_URI, etc.)
│   │   ├── database.py                  # ⭐ SQLAlchemy engine, AsyncSessionLocal
│   │   │
│   │   ├── auth/                        # JWT validation and RBAC
│   │   │   ├── jwt.py                   # ⭐ RS256 token validation via Cognito public key
│   │   │   ├── dependencies.py          # ⭐ get_current_user, require_role decorators
│   │   │   └── models.py                # UserModel with client_id, user_id, roles
│   │   │
│   │   ├── models/                      # SQLAlchemy ORM models (PostgreSQL tables)
│   │   │   ├── __init__.py
│   │   │   ├── client.py                # Client (multi-tenant container)
│   │   │   ├── legal_entity.py          # Legal entity (divisions, subsidiaries)
│   │   │   ├── bank.py                  # Bank (financial institutions)
│   │   │   ├── account.py               # Account (bank accounts) — includes od_limit, od_utilised_amount
│   │   │   ├── statement.py             # Statement (daily closing balance) — balance_after required for forecast
│   │   │   ├── transaction.py           # Transaction (individual entries)
│   │   │   ├── ar_data.py               # AR Schedule (accounts receivable aging)
│   │   │   ├── ap_data.py               # AP Schedule (accounts payable aging)
│   │   │   ├── manual_assumption.py     # Manual assumption (user-entered forecast assumptions) — includes confidence_pct
│   │   │   ├── source_file.py           # Source file (audit trail for uploads)
│   │   │   ├── job_status.py            # Job status (async job tracking) — result_id links to MongoDB
│   │   │   ├── audit_log.py             # Audit log (append-only event trail)
│   │   │   ├── system_config.py         # System config (forecast_confidence_threshold, warning_threshold_pct, etc.)
│   │   │   ├── fx_rates.py              # FX rates (currency conversion)
│   │   │   ├── investment.py            # Investment policy & cutoff
│   │   │   └── users.py                 # User (Cognito principal)
│   │   │
│   │   ├── routers/                     # FastAPI route modules (registered in main.py)
│   │   │   ├── __init__.py
│   │   │   ├── forecast.py              # ⭐ POST /api/forecast/request, GET /api/forecast/{id}, assumptions CRUD
│   │   │   ├── recommendations.py       # POST /api/recommendations/request, approve, reject, override
│   │   │   ├── variance.py              # POST /api/forecast/variance/request
│   │   │   ├── cfo_summary.py           # GET /api/cfo/report/{id}, POST /api/cfo/briefing/email
│   │   │   └── chat_proxy.py            # POST /api/chat/stream (proxy to AI Backend)
│   │   │
│   │   ├── routes/                      # Additional route modules (registered in main.py)
│   │   │   ├── accounts.py              # GET /api/accounts, POST, PUT, DELETE
│   │   │   ├── entities.py              # GET /api/entities, POST, PUT
│   │   │   ├── config.py                # GET/PUT /api/config/system, fx-rates, investment-policy
│   │   │   ├── files.py                 # POST /api/files/upload, GET /api/files/{id}
│   │   │   ├── jobs.py                  # GET /api/jobs/{id} (generic job status)
│   │   │   ├── audit.py                 # GET /api/audit/log (audit trail)
│   │   │   ├── metadata.py              # GET /api/metadata (clients, entities, banks, etc.)
│   │   │   └── health.py                # GET /health
│   │   │
│   │   ├── jobs/                        # Job publishing (async queue interface)
│   │   │   ├── __init__.py
│   │   │   ├── interface.py             # JobPublisher abstract base class
│   │   │   ├── in_process.py            # ⭐ InProcessJobPublisher (development; direct in-memory queue)
│   │   │   └── registry.py              # Job type mappings (forecast → run_forecast_job, etc.)
│   │   │
│   │   ├── services/                    # Business logic modules
│   │   │   ├── __init__.py
│   │   │   ├── audit_service.py         # write_audit_event (append to audit_log)
│   │   │   ├── recommendation_service.py # approve_recommendation, reject_recommendation, etc.
│   │   │   ├── cache.py                 # Simple in-memory cache
│   │   │   │
│   │   │   ├── csv_parsers/             # CSV file parsers
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base_parser.py       # Abstract BaseParser
│   │   │   │   ├── bank_balance_parser.py # Parses: date, account, balance
│   │   │   │   ├── ar_parser.py         # Parses: customer, due_date, amount
│   │   │   │   └── ap_parser.py         # Parses: vendor, due_date, amount
│   │   │   │
│   │   │   ├── file_parsers/            # Bank statement parsers (BAI2, MT940, camt.053)
│   │   │   │   ├── __init__.py
│   │   │   │   ├── bai2_parser.py       # Parses BAI2 format (bank balance)
│   │   │   │   ├── mt940_parser.py      # Parses MT940 format (transactions, balance)
│   │   │   │   └── camt053_parser.py    # Parses camt.053 format (transactions, balance)
│   │   │   │
│   │   │   └── file_format_detector.py  # Detects file format (CSV, BAI2, MT940, camt.053)
│   │   │
│   │   ├── middleware/                  # FastAPI middleware
│   │   │   ├── __init__.py
│   │   │   └── audit_middleware.py      # Captures user_id from JWT; injects into audit events
│   │   │
│   │   ├── mongo/                       # MongoDB connection
│   │   │   ├── __init__.py
│   │   │   └── client.py                # MongoClient singleton, get_mongo_db dependency
│   │   │
│   │   ├── utils/                       # Utilities
│   │   │   ├── __init__.py
│   │   │   └── fixtures.py              # Seed test data (loaded on startup)
│   │   │
│   │   └── __pycache__/
│   │
│   ├── alembic/                         # ⭐ SQL migrations (Alembic)
│   │   ├── versions/                    # Migration files
│   │   │   ├── 001_create_core_tables.py      # client, legal_entity, bank, users, account, statement, transaction, source_file
│   │   │   ├── 002_create_ar_ap_schedules.py  # ar_schedule, ap_schedule, manual_assumptions
│   │   │   ├── 003_create_fx_rates_config.py  # fx_rates, system_config
│   │   │   ├── 004_create_job_status.py       # job_status (async job tracking)
│   │   │   ├── 005_create_investment_policy.py # investment_policy, investment_cutoff
│   │   │   ├── 006_create_audit_log.py        # audit_log (append-only)
│   │   │   └── 007_add_forecast_assumption_columns.py # Add date, updated_at, deleted_at to manual_assumptions
│   │   ├── env.py                       # Alembic runtime config
│   │   ├── alembic.ini                  # Alembic configuration
│   │   └── script.py.mako               # Alembic migration template
│   │
│   ├── tests/                           # Unit & integration tests
│   │   ├── conftest.py                  # pytest fixtures
│   │   ├── test_forecast_endpoints.py   # Forecast router tests
│   │   ├── test_recommendations_endpoints.py
│   │   └── ...
│   │
│   ├── .env.example                     # Environment variables template
│   ├── requirements.txt                 # Python dependencies
│   ├── Dockerfile                       # Container image
│   └── manage.py                        # Utility (optional, for migrations)
│
├── ai-backend/                          # AI agent pipeline service (port 8001)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                      # ⭐ Entry point: FastAPI app, lifespan, MongoDB connection
│   │   ├── config.py                    # Environment variables (same as app-backend, plus ANTHROPIC_API_KEY)
│   │   ├── database.py                  # ⭐ Read-only PostgreSQL connection (no writes)
│   │   │
│   │   ├── agents/                      # ⭐ Agent implementations (8 agents total)
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  # ⭐ AgentBase, AgentState (shared state object)
│   │   │   ├── daily_cash_position.py   # Agent 1: Consolidate account balances
│   │   │   ├── forecast.py              # ⭐ Agent 2 (Session 13): 30-day forecast from assumptions
│   │   │   ├── liquidity_risk.py        # Agent 3: Risk scoring (shortfall detection, coverage ratio)
│   │   │   ├── policy_control.py        # Agent 7: Policy validation (blocks recommendations)
│   │   │   ├── action_recommendation.py # Agent 4: Generate recommendations (mocked LLM)
│   │   │   ├── variance_explanation.py  # Agent 5: Explain forecast vs. actual (mocked LLM)
│   │   │   ├── cfo_summary.py           # Agent 6: Executive summary (mocked LLM)
│   │   │   └── treasury_continuity.py   # Agent 8: Continuity check (daily briefing aggregation)
│   │   │
│   │   ├── jobs/                        # ⭐ Job handlers (mapped from job_type)
│   │   │   ├── __init__.py
│   │   │   ├── registry.py              # ⭐ JOB_REGISTRY: maps job_type → handler function
│   │   │   ├── forecast_job.py          # run_forecast_job handler (Agent 2)
│   │   │   ├── daily_cash_job.py        # run_cash_position_job handler (Agent 1)
│   │   │   ├── liquidity_risk_job.py    # run_liquidity_risk_job handler (Agent 3)
│   │   │   ├── recommendation_job.py    # run_recommendation_job handler (Agent 4)
│   │   │   ├── variance_job.py          # run_variance_explanation_job handler (Agent 5)
│   │   │   ├── cfo_summary_job.py       # run_cfo_summary_job handler (Agent 6)
│   │   │   └── consumer.py              # ⭐ SQS consumer loop (or InProcess for dev)
│   │   │
│   │   ├── routes/                      # FastAPI routes
│   │   │   ├── health.py                # GET /health
│   │   │   └── chat.py                  # ⭐ POST /chat/stream (SSE streaming, real-time LLM)
│   │   │
│   │   ├── sqs/                         # SQS consumer (production)
│   │   │   ├── __init__.py
│   │   │   └── consumer.py              # Async SQS consumer loop
│   │   │
│   │   ├── mongo/                       # MongoDB connection
│   │   │   ├── __init__.py
│   │   │   └── client.py                # MongoClient singleton, get_mongo_db dependency
│   │   │
│   │   └── __pycache__/
│   │
│   ├── tests/                           # Unit & integration tests
│   │   ├── conftest.py
│   │   ├── test_forecast_agent.py       # Agent 2 tests (6 test cases)
│   │   ├── test_daily_cash_agent.py
│   │   ├── test_liquidity_risk_agent.py
│   │   └── ...
│   │
│   ├── .env.example
│   ├── requirements.txt
│   ├── Dockerfile
│   └── manage.py                        # Utility (optional)
│
└── docs/
    ├── session-13-handoff-FINAL.md      # Session 13 build summary
    └── developer-guide/                 # 📖 THIS DOCUMENTATION
        ├── README.md                    # Index
        ├── 01-architecture.md           # System design & agent pipeline
        ├── 02-database-schema.md        # PostgreSQL tables & MongoDB collections
        ├── 03-api-reference.md          # All endpoints
        ├── 04-repo-structure.md         # This file
        ├── 05-config-and-env.md         # Environment variables
        └── 06-frontend-integration-guide.md # For frontend developers
```

---

## Key Entry Points

### Startup: App Backend

```python
# app-backend/app/main.py (lines 1–79)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect PostgreSQL, MongoDB, load fixtures
    # Shutdown: disconnect MongoDB, dispose engine

app = FastAPI(title="Core Cash App Backend", ...)
app.add_middleware(AuditMiddleware)  # Capture user_id
app.add_middleware(CORSMiddleware)   # Allow all origins
app.include_router(...)              # Register all routers + routes
```

**Routers Registered** (from main.py):
- `health.router` → GET /health
- `accounts.router` → /api/accounts
- `entities.router` → /api/entities
- `config.router` → /api/config/*
- `jobs.router` → /api/jobs/*
- `files.router` → /api/files/*
- `liquidity_risk.router` → /api/liquidity-risk/*
- `audit.router` → /api/audit/log
- `metadata.router` → /api/metadata
- `recommendations.router` → /api/recommendations/*
- `forecast.router` → /api/forecast/*
- `cfo_summary.router` → /api/cfo/*
- `variance.router` → /api/forecast/variance/*
- `chat_proxy.router` → /api/chat/*

### Startup: AI Backend

```python
# ai-backend/app/main.py (lines 1–57)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify read-only PostgreSQL, connect MongoDB
    # Shutdown: disconnect MongoDB, dispose engine

app = FastAPI(title="Core Cash AI Backend", ...)
app.include_router(health.router)
app.include_router(chat.router, prefix="/chat", tags=["Chat"])

# Also: start consumer loop (InProcess or SQS) to process jobs
```

---

## How to Add a New Agent

### 1. Create Agent Class

**File**: `ai-backend/app/agents/my_new_agent.py`

```python
from app.agents.base import AgentBase, AgentState

class MyNewAgent(AgentBase):
    async def run(self, state: AgentState) -> AgentState:
        # 1. Read from PostgreSQL (read-only)
        # 2. Read from MongoDB (latest docs)
        # 3. Perform calculations or LLM call
        # 4. Write to MongoDB collection
        # 5. Update AgentState
        # 6. Return state
        pass
```

### 2. Create Job Handler

**File**: `ai-backend/app/jobs/my_new_job.py`

```python
async def run_my_new_job(job_envelope, db, mongo):
    agent = MyNewAgent()
    state = AgentState()
    result_state = await agent.run(state)
    # Write result_id to job_status table (handled by consumer)
    return result_state
```

### 3. Register Job Type

**File**: `ai-backend/app/jobs/registry.py`

```python
from app.jobs.my_new_job import run_my_new_job

JOB_REGISTRY = {
    "forecast": run_forecast_job,
    "my_new_job_type": run_my_new_job,  # Add here
}
```

### 4. Add Job Type Enum

**File**: `shared/core_cash_shared/enums.py`

```python
class JobType(str, Enum):
    MY_NEW_JOB = "my_new_job_type"  # Add here
```

### 5. Create App Backend Endpoint

**File**: `app-backend/app/routers/my_new_router.py`

```python
@router.post("/api/my-endpoint/request", status_code=202)
async def request_my_job(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(require_role([...]))
):
    # 1. Create JobStatus record
    # 2. Publish JobEnvelope to InProcessJobPublisher
    # 3. Return 202 with request_id
    pass

@router.get("/api/my-endpoint/{request_id}")
async def get_my_job_result(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    mongo_db = Depends(get_mongo_db),
    current_user: UserModel = Depends(get_current_user)
):
    # 1. Poll job_status
    # 2. If completed, fetch result from MongoDB
    # 3. Return result or polling status
    pass
```

### 6. Register Router

**File**: `app-backend/app/main.py`

```python
from app.routers import my_new_router

app.include_router(my_new_router.router)
```

---

## How to Add a New App Backend Endpoint

### 1. Create Router Module

**File**: `app-backend/app/routers/new_feature.py` (or add to existing router)

```python
from fastapi import APIRouter, Depends, HTTPException
from app.auth.dependencies import get_current_user, require_role
from app.database import get_db

router = APIRouter()

@router.get("/api/new-endpoint", tags=["NewFeature"])
async def get_new_data(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    # Implementation
    pass
```

### 2. Register Router

**File**: `app-backend/app/main.py`

```python
from app.routers import new_feature

app.include_router(new_feature.router)
```

---

## How Migrations Work

### Create a Migration

```bash
cd app-backend
alembic revision --autogenerate -m "Add new_column to accounts"
# Generates: alembic/versions/008_add_new_column_to_accounts.py
```

### Review Migration

**File**: `alembic/versions/008_add_new_column_to_accounts.py`

```python
def upgrade() -> None:
    op.add_column('account', sa.Column('new_column', sa.String(50)))

def downgrade() -> None:
    op.drop_column('account', 'new_column')
```

### Run Migrations

```bash
# Upgrade to latest
alembic upgrade head

# Upgrade to specific version
alembic upgrade 008

# Downgrade
alembic downgrade -1
```

### Important Notes

- Migrations run on startup (see app-backend/app/main.py lifespan)
- Always test upgrade AND downgrade paths
- Naming: use descriptive revision messages
- Never edit migration files manually after creation (use new revision)

---

## How to Add a MongoDB Collection

MongoDB has no schema enforcement, but each collection should be documented in `docs/developer-guide/02-database-schema.md`.

### 1. Decide Collection Name & Shape

**Example**: `forecast_runs`

```json
{
  "_id": ObjectId,
  "forecast_run_id": "uuid",
  "entity_id": "uuid",
  "data_status": "partial|blocked",
  "forecast_rows": [...],
  ...
}
```

### 2. Write to Collection (in Agent)

```python
# In agent run() method:
result_doc = {
    "forecast_run_id": forecast_run_id,
    "entity_id": entity_id,
    # ... fields ...
}
collection = mongo_db["forecast_runs"]
result = await collection.insert_one(result_doc)
state["forecast_run_id"] = result.inserted_id
```

### 3. Read from Collection (in App Backend)

```python
# In route handler:
collection = mongo_db["forecast_runs"]
doc = await collection.find_one({"_id": ObjectId(mongo_id)})
return {"result": doc}
```

### 4. Document in Schema Reference

**File**: `docs/developer-guide/02-database-schema.md` (Section B)

Add collection documentation with:
- Purpose
- Document shape (JSON example)
- Written by (which agent)
- Read by (which services)
- Retention policy (TTL, delete after N days, etc.)

---

## Shared Package Installation

### Development

```bash
cd shared
pip install -e .
```

### In Docker

```dockerfile
COPY shared /app/shared
RUN pip install -e /app/shared
```

### After Changes

The shared package needs to be re-installed for both services:
1. Update `shared/core_cash_shared/schemas/forecast.py` (or any file)
2. Reinstall: `pip install -e ./shared`
3. Both app-backend and ai-backend will pick up the new schemas

---

## Testing

### Unit Tests (Agents)

```bash
cd ai-backend
pytest tests/test_forecast_agent.py -v
```

### Unit Tests (Endpoints)

```bash
cd app-backend
pytest tests/test_forecast_endpoints.py -v
```

### Integration Tests (Full Pipeline)

Spawn both services, upload a bank statement, request forecast, poll result.

### Test Database

Tests use a separate PostgreSQL database (configured via TEST_DATABASE_URL in .env.test).

---

## File Size Summary

```
app-backend/
  app/agents/ (0 agents; agents in ai-backend)
  app/routers/ (6 files: forecast, recommendations, variance, cfo_summary, chat_proxy, + __init__)
  app/routes/ (8 files: accounts, entities, config, files, jobs, audit, metadata, health)
  app/models/ (14 ORM model files)
  app/services/ (4 main + file parsers; 8 total)
  → ~60 Python files total

ai-backend/
  app/agents/ (8 agent files)
  app/jobs/ (8 job handlers + registry + consumer)
  app/routes/ (2 files: health, chat)
  → ~20 Python files total

shared/
  schemas/ (6 Pydantic model files)
  → ~6 Python files total
```

---

## Critical Files Checklist

| File | Purpose | Edit? |
|------|---------|-------|
| `app-backend/app/main.py` | FastAPI app setup | Only to register new routers |
| `app-backend/app/database.py` | SQLAlchemy engine | Rarely; connect string only |
| `app-backend/app/auth/jwt.py` | JWT validation | Never (unless Cognito config changes) |
| `ai-backend/app/main.py` | FastAPI app setup | Only to register new routes |
| `ai-backend/app/jobs/registry.py` | Job type mapping | Always when adding new agent |
| `app-backend/alembic/versions/*` | Migrations | Always for schema changes |
| `shared/core_cash_shared/enums.py` | Enums (JobType, etc.) | When adding new job type |
| `shared/core_cash_shared/error_codes.py` | Error constants | When adding new error |

Next: [Configuration and Environment Variables →](05-config-and-env.md)
