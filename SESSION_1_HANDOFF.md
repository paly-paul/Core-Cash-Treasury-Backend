# Session 1 Handoff: Core Cash Agent Backend Foundation

## What Was Built

### Shared Library (`/shared`)
Core Python library installed as local editable dependency by both services.

- `pyproject.toml` — Package metadata and dependencies
- `core_cash_shared/__init__.py` — Public exports
- `core_cash_shared/enums.py` — Seven enums: AccountStatus, JobType, JobStatus, ApprovalStatus, RefreshFrequency, DataConfidence, RiskLevel
- `core_cash_shared/error_codes.py` — 22 central error code constants (auth, validation, business logic, jobs, data)
- `core_cash_shared/schemas/errors.py` — ErrorDetail, ErrorResponse Pydantic models
- `core_cash_shared/schemas/jobs.py` — JobEnvelope (SQS-compatible), JobStatusResponse

### App Backend (`/app-backend`)
FastAPI service: account/client/auth management, file uploads, job dispatch.

**Configuration & Database:**
- `pyproject.toml` — Dependencies: FastAPI, SQLAlchemy (asyncio), asyncpg, Alembic, python-jose, motor, boto3
- `.env.example` — Database, MongoDB, AWS Cognito, SQS settings
- `app/config.py` — Pydantic Settings (env-based configuration)
- `app/database.py` — Async SQLAlchemy engine, session factory, get_db dependency
- `app/mongo/client.py` — Motor AsyncIOMotorClient, collection creation, indexes
- `alembic.ini` — Alembic configuration
- `alembic/env.py` — Alembic async environment
- `alembic/script.py.mako` — Migration template
- `alembic/versions/` — Six migrations (see "Database Schema" below)

**Authentication:**
- `app/auth/jwt.py` — Cognito RS256 JWT validation (signature, iss, aud, exp checks)
- `app/auth/dependencies.py` — FastAPI depends: get_current_user, require_role factory
- `app/auth/models.py` — UserModel Pydantic schema

**Jobs & Queueing:**
- `app/jobs/interface.py` — Abstract JobPublisher interface
- `app/jobs/in_process.py` — InProcessJobPublisher using asyncio.create_task
- `app/jobs/registry.py` — Empty JOB_HANDLERS map (populated by agent sessions)

**Data Models:**
- `app/models/` — SQLAlchemy ORM models mirroring all tables: Client, LegalEntity, Bank, Users, Account, Statement, Transaction, SourceFile

**Routes:**
- `app/routes/health.py` — GET /health → {"status":"ok","service":"app-backend","version":"1.0.0"}

**Main App:**
- `app/main.py` — FastAPI app with lifespan context manager, CORS middleware, exception handler, route mounting

### AI Backend (`/ai-backend`)
FastAPI service: LangGraph agent orchestration, MongoDB writes, read-only PostgreSQL access.

**Configuration & Database:**
- `pyproject.toml` — Dependencies: FastAPI, SQLAlchemy, asyncpg, motor, langgraph, langchain-core, anthropic
- `.env.example` — Database (read-only), MongoDB, Anthropic API key, AWS region
- `app/config.py` — Pydantic Settings (env-based)
- `app/database.py` — Read-only SQLAlchemy engine, verify_read_only() startup check
- `app/mongo/client.py` — Motor client connection

**LangGraph Pipeline:**
- `app/graph/state.py` — AgentState TypedDict with job metadata + 7 output fields + errors dict
- `app/graph/pipeline.py` — 8 stub nodes wired in sequential MVP order; build_pipeline() compiles StateGraph
- `app/agents/base.py` — BaseAgent abstract class with run() method
- `app/agents/__init__.py` — Empty (subclasses added in later sessions)

**Job Execution:**
- `app/worker/dispatcher.py` — Empty AGENT_RUNNERS map (JobType → handler, populated later)
- `app/worker/runner.py` — run_agent_job() orchestrator: builds initial state, runs pipeline, writes to MongoDB agent_runs collection

**Routes:**
- `app/routes/health.py` — GET /health → {"status":"ok","service":"ai-backend","version":"1.0.0"}

**Main App:**
- `app/main.py` — FastAPI app with lifespan, CORS, exception handler, read-only DB verification on startup

---

## Interfaces Established

### JobPublisher Interface
```python
class JobPublisher(ABC):
    @abstractmethod
    async def publish(self, envelope: JobEnvelope) -> str:
        """Publish a job. Returns job_id."""
        ...
```

**Current Implementation:** InProcessJobPublisher (asyncio task dispatch)
**Future:** SQSJobPublisher(JobPublisher) when SQS replaces in-process

### JobEnvelope (SQS-Compatible)
```python
class JobEnvelope(BaseModel):
    job_id: str                          # UUID string
    job_type: JobType                    # Enum: cash_position, liquidity_risk, ...
    client_id: str
    user_id: str
    requested_at: datetime
    payload: Dict[str, Any]              # Job-specific data
```

### JobStatusResponse
```python
class JobStatusResponse(BaseModel):
    request_id: str
    status: JobStatus                    # queued | processing | completed | failed
    job_type: JobType
    requested_at: datetime
    completed_at: Optional[datetime]
    result_id: Optional[str]             # MongoDB _id when completed
    error: Optional[str]
```

### AgentState (LangGraph)
```python
class AgentState(TypedDict):
    job_id: str
    client_id: str
    user_id: str
    requested_at: datetime
    # Outputs (None until agent runs)
    cash_position: Optional[Dict[str, Any]]
    liquidity_risk: Optional[Dict[str, Any]]
    forecast: Optional[Dict[str, Any]]
    action_recommendations: Optional[Dict[str, Any]]
    variance_explanation: Optional[Dict[str, Any]]
    treasury_continuity: Optional[Dict[str, Any]]
    cfo_summary: Optional[Dict[str, Any]]
    # Errors
    errors: Dict[str, str]               # agent_name → error message
```

### Enum Values

**AccountStatus:** Green, Yellow, Red

**JobType:** cash_position, liquidity_risk, action_recommendation, variance_explanation, cfo_summary, treasury_continuity, daily_briefing

**JobStatus:** queued, processing, completed, failed

**ApprovalStatus:** Pending, Approved, Rejected

**RefreshFrequency:** Daily, Weekly, Monthly, Manual

**DataConfidence:** High, Medium, Low

**RiskLevel:** Low, Medium, High

### Error Codes (23 total)
- **Auth (4):** AUTH_TOKEN_MISSING, AUTH_TOKEN_INVALID, AUTH_TOKEN_EXPIRED, AUTH_PERMISSION_DENIED
- **Validation (4):** VALIDATION_REQUIRED_FIELD, VALIDATION_INVALID_FORMAT, VALIDATION_FILE_TOO_LARGE, VALIDATION_UNSUPPORTED_FORMAT
- **Business Logic (4):** OPENING_BALANCE_UNRESOLVED, FX_RATE_MISSING, INVESTMENT_POLICY_NOT_UPLOADED, ACCOUNT_RESTRICTED
- **Jobs (3):** JOB_NOT_FOUND, JOB_STILL_PROCESSING, JOB_FAILED
- **Data (2):** DATA_STALE, DATA_MISSING_FEED

---

## Database Schema

### PostgreSQL Tables (6 Migrations)

**Migration 001: Core Tables**
- `client` (id, name, slug, created_at)
- `legal_entity` (id, client_id, name, base_currency, country_code, created_at)
- `bank` (id, client_id, name, swift_code, created_at)
- `users` (id, client_id, email, cognito_sub, role, created_at)
  - Roles: Viewer, Analyst, TreasuryManager, CFO
- `account` (id, client_id, entity_id, bank_id, account_name, bank_account_number, currency, min_threshold, restricted_flag, od_limit, od_utilised_amount, refresh_frequency, include_in_cash_position, is_active, created_at)
  - **Note:** od_headroom is NOT stored — computed at runtime as `od_limit - od_utilised_amount`
  - refresh_frequency values: Daily, Weekly, Monthly, Manual
- `statement` (id, account_id, statement_date, closing_balance, available_balance, currency, source, ingested_at)
  - Unique constraint on (account_id, statement_date)
- `transaction` (id, account_id, statement_id, transaction_date, value_date, amount, direction, description, reference, created_at)
  - direction: credit | debit
- `source_file` (id, client_id, uploaded_by, file_type, file_format, filename, rows_imported, status, error_message, uploaded_at)

**Migration 002: AR/AP Schedules**
- `ar_schedule` (id, client_id, entity_id, counterparty_name, expected_date, amount, currency, category, source_file_id, created_at)
- `ap_schedule` (id, client_id, entity_id, vendor_name, due_date, amount, currency, category, source_file_id, created_at)
- `manual_assumptions` (id, client_id, entity_id, description, amount, currency, expected_date, direction, confidence_pct, created_by, created_at)
  - direction: inflow | outflow
  - confidence_pct: 0.00–100.00 (only >=50 used in forecasts)

**Migration 003: FX Rates & System Config**
- `fx_rates` (id, client_id, currency_from, currency_to, rate, rate_date, entered_by, entered_at)
  - Unique constraint on (client_id, currency_from, rate_date)
- `system_config` (id, client_id, config_key, config_val, updated_by, updated_at)
  - Unique constraint on (client_id, config_key)
  - Seed defaults per client: forecast_confidence_threshold, warning_threshold_pct, significant_outflow_pct

**Migration 004: Job Status Tracking**
- `job_status` (id, client_id, job_id, job_type, status, requested_by, requested_at, completed_at, result_id, error_message)
  - Indexes: (job_id), (client_id, status)

**Migration 005: Investment Policy**
- `investment_policy` (id, client_id, entity_id, version, document_url, uploaded_by, uploaded_at, is_active)
- `entity_investment_cutoffs` (id, entity_id, cutoff_time, timezone, investment_account_id, updated_by, updated_at)

**Migration 006: Audit Log**
- `audit_log` (id, client_id, user_id, action, entity_type, entity_id, before_state, after_state, ip_address, created_at)
  - Indexes: (client_id), (created_at)

---

## MongoDB Collections & Indexes

**Collections Created (App Backend Startup):**
1. `agent_runs` — Final state and results of executed jobs
2. `recommendations` — Action recommendations with approval status
3. `cfo_reports` — CFO-level summaries
4. `daily_briefings` — Daily intelligence briefs
5. `variance_reports` — Variance analysis outputs
6. `job_status_mirror` — Mirror of PostgreSQL job_status for read efficiency

**Indexes Created:**
- `agent_runs`: (client_id, job_id), (client_id, created_at DESC)
- `recommendations`: (client_id, approval_status), (client_id, created_at DESC)
- `cfo_reports`: (client_id, created_at DESC)
- `daily_briefings`: (client_id, created_at DESC)
- `variance_reports`: (client_id, created_at DESC)

---

## Assumptions Made

1. **Cognito JWT Validation:** Assumed RS256 algorithm, standard JWT structure (sub, email, cognito:groups, iss, aud, exp claims). No JWKS caching — fetches on each validation.

2. **Async All The Way:** Both FastAPI services use async/await exclusively (AsyncSession, Motor, asyncio.create_task). No sync code paths.

3. **Read-Only AI Backend DB:** PostgreSQL user for AI Backend must have SELECT-only grants. Startup verification raises RuntimeError if INSERT succeeds.

4. **Local Editable Dependency:** Both services install `/shared` via `pip install -e ../shared`. No separate package publication.

5. **No ANTHROPIC_API_KEY Import:** .env.example includes the key; neither service imports or uses it. Reserved for Session 12+.

6. **Empty Job Handlers & Agent Runners:** registry.py and dispatcher.py are empty dicts. Each agent session populates its portion.

7. **Sequential MVP Pipeline Order:** All 8 agents run in fixed order regardless of job_type. Future: routing by job_type to subset of agents.

8. **MongoDB TTL Not Set:** Collections have no TTL indexes. Sessions 7+ will add data retention policies.

9. **No User Onboarding:** Users table exists but has no signup/invite flow. Seeded via API calls or manual DB insert.

10. **Cognito Roles → DB Column:** User.role is set from cognito:groups[0] on token validation. No RBAC database.

---

## What Session 2 Must Know Before Starting

1. **Shared Library Is Ready:** Import any enum, error code, or schema without hesitation:
   ```python
   from core_cash_shared import JobType, error_codes
   from core_cash_shared.schemas.jobs import JobEnvelope
   ```

2. **Database Migrations Are One-Way:** All 6 migrations run in order. Do not modify existing migration files (001–006). New migrations go in 007+.

3. **LangGraph Stubs Are Wired:** The graph compiles successfully. Each node is an async function returning AgentState. Sessions 2–11 replace stubs with real agents.

4. **JWT Validation Doesn't Cache JWKS:** Each /token validation call does a fresh HTTP request to Cognito. Session 9 should add caching.

5. **App Backend Job Dispatch Is In-Process:** `InProcessJobPublisher.publish()` creates an asyncio task. No SQS yet. The interface is ready for SQS swap without changing agent code.

6. **AI Backend Runs the Graph, App Backend Dispatches:** App Backend publishes a JobEnvelope; AI Backend's dispatcher routes it to a LangGraph run. Job status flows back to PostgreSQL job_status table and MongoDB job_status_mirror.

7. **No Agent Logic Exists Yet:** All 8 nodes are stubs. No LLM calls, no database reads for cash position, no nothing. Sessions 2–11 populate each node.

8. **MongoDB Collections Exist:** Startup creates them with indexes. Don't manually create collections in later sessions.

9. **Read-Only AI Backend:** The startup check will fail if the database user can INSERT. Use a separate read-only role.

10. **Error Codes Are Central:** Add new error codes to error_codes.py, not scattered throughout. Every exception raised to the user should use a code from the registry.

---

## Open Items & Deferred Decisions

**None.** This session builds exactly what was specified: foundation only.

### Deferred to Later Sessions (By Design)
- **Session 2:** Cash Position Agent (agent_1 stub)
- **Session 3:** Forecast Agent (agent_2 stub)
- **Session 4:** Liquidity Risk Agent (agent_3 stub)
- **Sessions 5–11:** Remaining agents (4–8) and supporting logic
- **Session 12+:** LLM integration (Anthropic Claude), prompt engineering
- **SQS Session:** Replace InProcessJobPublisher with SQSJobPublisher

---

## Verification Checklist (All Passed)

- ✓ Shared library installs cleanly
- ✓ App Backend imports core_cash_shared without error
- ✓ AI Backend imports core_cash_shared without error
- ✓ All 6 migrations created (001–006)
- ✓ od_headroom column does NOT exist (computed at runtime)
- ✓ /health endpoints defined for both services
- ✓ JWT validation logic in place (RS256, exp, iss checks)
- ✓ Role-based access control factory created
- ✓ JobPublisher interface defined; InProcessJobPublisher implements it
- ✓ MongoDB client with collection/index creation
- ✓ LangGraph pipeline compiles; 8 nodes wired in sequence
- ✓ AgentState TypedDict captures all outputs and errors
- ✓ Read-only verification on AI Backend startup
- ✓ ANTHROPIC_API_KEY in .env.example but not imported anywhere
- ✓ Error codes centralized (23 total)
- ✓ Lifespan context managers for database connection lifecycle
- ✓ CORS middleware enabled on both services
- ✓ Exception handlers return ErrorResponse with ErrorDetail

---

**End of Session 1. Ready for Session 2: Cash Position Agent.**
