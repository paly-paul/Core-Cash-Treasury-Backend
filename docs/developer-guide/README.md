# Core Cash Agent — Developer Guide

**Welcome to the Core Cash Agent backend documentation!** This guide covers architecture, APIs, database schema, configuration, and frontend integration.

---

## Quick Navigation

| Document | Purpose | Audience |
|----------|---------|----------|
| **[01-architecture.md](01-architecture.md)** | System design, 8-agent pipeline, dual-service architecture, request lifecycle | All engineers |
| **[02-database-schema.md](02-database-schema.md)** | PostgreSQL tables (entities, accounts, statements, etc.) + MongoDB collections (forecast_runs, recommendations, etc.) | Backend engineers, database admins |
| **[03-api-reference.md](03-api-reference.md)** | Complete endpoint documentation (auth, cash position, forecast, recommendations, chat, config, audit) | All engineers |
| **[04-repo-structure.md](04-repo-structure.md)** | File tree, entry points, how to add agents/endpoints, migrations, testing | Backend engineers |
| **[05-config-and-env.md](05-config-and-env.md)** | Environment variables, database connections, Cognito setup, system_config keys, startup behavior | DevOps, backend engineers |
| **[06-frontend-integration-guide.md](06-frontend-integration-guide.md)** | JWT auth, async polling, SSE chat, recommendation approval, business rules, error handling | Frontend engineers |

---

## Start Here

### New to Core Cash?

1. Read **[01-architecture.md](01-architecture.md)** first (15 min)
   - Understand the two services (App Backend + AI Backend)
   - Learn the 8-agent pipeline
   - See request lifecycle & authentication flow

2. Skim **[02-database-schema.md](02-database-schema.md)** (10 min)
   - Understand PostgreSQL tables & MongoDB collections
   - Know which agents write which collections

3. Pick one of:
   - **Backend work?** → Read **[04-repo-structure.md](04-repo-structure.md)** + **[05-config-and-env.md](05-config-and-env.md)**
   - **Frontend work?** → Read **[06-frontend-integration-guide.md](06-frontend-integration-guide.md)** + **[03-api-reference.md](03-api-reference.md)**
   - **DevOps work?** → Read **[05-config-and-env.md](05-config-and-env.md)**
   - **API questions?** → Jump to **[03-api-reference.md](03-api-reference.md)**

---

## Key Concepts

### Two Services
- **App Backend (port 8000)**: User-facing API, PostgreSQL R/W, job publishing
- **AI Backend (port 8001)**: Agent pipeline, PostgreSQL R/O, MongoDB R/W

### Eight Agents (Async Pipeline)
1. **Daily Cash Position** (Agent 1): Consolidate account balances → MongoDB
2. **Forecast** (Agent 2): 30-day projection from assumptions → MongoDB
3. **Liquidity Risk** (Agent 3): Risk scoring & shortfall detection → MongoDB
4. **Action Recommendation** (Agent 4): Generate recommendations (mocked LLM) → MongoDB
5. **Variance Explanation** (Agent 5): Why forecast missed actuals (mocked LLM) → MongoDB
6. **CFO Summary** (Agent 6): Executive brief (mocked LLM) → MongoDB
7. **Treasury Continuity** (Agent 7): Policy validation (blocks recommendations) → internal state
8. **Daily Briefing** (Agent 8): Aggregate & email → MongoDB

### Job Lifecycle
```
POST /api/forecast/request
  ↓
App Backend publishes JobEnvelope
  ↓
AI Backend consumer dequeues
  ↓
Agent 2 (Forecast) executes
  ↓
Result written to MongoDB
  ↓
GET /api/forecast/{job_id} returns result
```

### Authentication
- **JWT from Cognito** (RS256 signature)
- **RBAC roles**: Viewer, Analyst, TreasuryManager, CFO
- **Every API request** includes: `Authorization: Bearer <token>`

---

## Common Tasks

### "I want to add a new endpoint"
→ See **[04-repo-structure.md](04-repo-structure.md)** → "How to Add a New App Backend Endpoint"

### "I want to create a new agent"
→ See **[04-repo-structure.md](04-repo-structure.md)** → "How to Add a New Agent"

### "What endpoints are available?"
→ See **[03-api-reference.md](03-api-reference.md)** (complete endpoint listing with examples)

### "How do I handle async requests on the frontend?"
→ See **[06-frontend-integration-guide.md](06-frontend-integration-guide.md)** → "Async Request Pattern"

### "What are the database tables?"
→ See **[02-database-schema.md](02-database-schema.md)** → "Section A — PostgreSQL Tables"

### "How do I configure environment variables?"
→ See **[05-config-and-env.md](05-config-and-env.md)**

### "What are the system_config keys?"
→ See **[05-config-and-env.md](05-config-and-env.md)** → "System Configuration"

### "How do migrations work?"
→ See **[04-repo-structure.md](04-repo-structure.md)** → "How Migrations Work"

### "How do I add a MongoDB collection?"
→ See **[04-repo-structure.md](04-repo-structure.md)** → "How to Add a MongoDB Collection"

---

## Critical Rules

### Backend
1. ✅ AI Backend reads PostgreSQL only (read-only connection)
2. ✅ App Backend reads/writes PostgreSQL
3. ✅ Both services read/write MongoDB
4. ✅ Agents write to MongoDB collections
5. ❌ No autonomous execution; all recommendations require approval

### Frontend
1. ✅ Always include JWT token in every request
2. ✅ Use polling pattern for async jobs (POST → GET poll)
3. ❌ Never call AI Backend directly; go through App Backend
4. ❌ Never add `od_headroom` to `usable_cash` (separate figures)
5. ✅ Warning threshold is always 70% (never 80%)
6. ❌ Never show `blocked_count` or `blocked_reasons` in UI

### Database
1. ✅ Manual assumptions are soft-deleted (set `deleted_at`)
2. ✅ Audit log is append-only (no UPDATE/DELETE)
3. ✅ Only one active investment policy per entity (is_active flag)
4. ✅ `od_headroom` is computed, not stored (od_limit - od_utilised_amount)
5. ❌ Don't hardcode default values; read from system_config

---

## Architecture at a Glance

```
Browser (JWT from Cognito)
  ↓
App Backend (8000)
  ├─ Auth: Validate JWT RS256
  ├─ Routes: /api/forecast, /recommendations, /chat, etc.
  ├─ Write: PostgreSQL job_status, audit_log, manual_assumptions
  ├─ Read: PostgreSQL (all), MongoDB (poll results)
  └─ Publish: JobEnvelope → InProcessJobPublisher
                ↓
            AI Backend (8001)
              ├─ Consumer: Dequeue jobs
              ├─ Agents: Run Agent 1–8
              ├─ Write: MongoDB (forecast_runs, recommendations, etc.)
              └─ Chat: SSE streaming (real-time LLM)

Databases:
  PostgreSQL: job_status, audit_log, manual_assumptions, system_config, etc.
  MongoDB: forecast_runs, recommendations, cfo_reports, daily_briefings, etc.
```

---

## Session History

All development is tracked in session handoff documents.

| Session | Work | Status |
|---------|------|--------|
| S0–S2 | Monorepo scaffold, dual-service FastAPI | ✅ Complete |
| S3 | DB migrations + Agent 1 | ✅ Complete |
| S4 | Agent 3 (Liquidity Risk) | ✅ Complete |
| S5 | CSV parsers (AR, AP, bank balance) | ✅ Complete |
| S6 | Agent 4 (Recommendation, mocked) + Agent 8 | ✅ Complete |
| S7 | Forecast scaffold + Assumptions CRUD | ✅ Complete |
| S8 | Config endpoints (FX, investment policy) | ✅ Complete |
| S9 | Agent 6 (CFO Summary, mocked) + Agent 7 | ✅ Complete |
| S10 | Agent 5 (Variance Explanation, mocked) | ✅ Complete |
| S11 | Audit log + Approvals workflow | ✅ Complete |
| S12 | Chat SSE endpoint (mocked LLM) | ✅ Complete |
| **S13** | **Agent 2 Forecast scaffold** | **✅ CURRENT** |
| S14 | Forecast full ML implementation | ⏳ Pending |
| S15 | Real LLM wiring (Claude API) | 🔒 Post-MVP |

See **[../session-13-handoff-FINAL.md](../session-13-handoff-FINAL.md)** for the latest build summary.

---

## Troubleshooting

### "Failed to verify read-only database"
- **Cause**: AI Backend detected write permission
- **Fix**: Ensure AI Backend PostgreSQL user has SELECT-only permissions

### "Forecast is blocked with OPENING_BALANCE_UNRESOLVED"
- **Cause**: No bank statement with closing balance exists
- **Fix**: Upload a bank statement file (BAI2, MT940, or camt.053)

### "Recommendation has already been actioned" (409)
- **Cause**: Another user approved/rejected the same recommendation
- **Fix**: Refresh recommendation list; show "Already actioned by [user]" message

### "ANTHROPIC_API_KEY not set"
- **Expected behavior**: Service starts with placeholder API key
- **Agents return**: Mock responses (all numeric data still accurate)
- **Fix for production**: Set real API key in .env

### "JWT token invalid"
- **Cause**: Cognito public key changed or token signed with different key
- **Fix**: Verify COGNITO_USER_POOL_ID and COGNITO_REGION match Cognito setup

---

## Glossary

| Term | Meaning |
|------|---------|
| **Agent** | Async microservice that reads from PostgreSQL/MongoDB, performs analysis, writes to MongoDB |
| **Job** | Async unit of work (forecast request, recommendation request, etc.) |
| **Job Status** | Tracks job progress (queued → processing → completed/failed) |
| **JobEnvelope** | Message containing job_id, job_type, payload; sent via queue |
| **Entity** | Legal entity / business division (often multi-entity clients) |
| **Account** | Bank account (has balance, OD limit, etc.) |
| **Assumption** | Manual forecast assumption (e.g., "bonus payout on Aug 31") |
| **Recommendation** | Action suggestion (e.g., "invest surplus") requiring approval |
| **Forecast** | 30-day cash projection |
| **Variance** | Analysis of forecast vs. actual |
| **Policy** | Investment policy (limits, cutoff dates, thresholds) |
| **SSE** | Server-Sent Events (real-time streaming from server to browser) |
| **JWT** | JSON Web Token (Cognito auth token) |

---

## Resources

- **AWS Cognito**: https://docs.aws.amazon.com/cognito/latest/developerguide/
- **FastAPI**: https://fastapi.tiangolo.com/
- **SQLAlchemy**: https://docs.sqlalchemy.org/
- **MongoDB**: https://docs.mongodb.com/
- **Pydantic**: https://docs.pydantic.dev/
- **LangGraph**: https://github.com/langchain-ai/langgraph

---

## Feedback & Questions

- **Found a documentation gap?** Open an issue or PR
- **Have questions?** Check the relevant doc section first; then ask the team
- **Want to contribute?** Follow the architecture & style from existing docs

---

**Last updated**: August 24, 2026 (Session 13)
