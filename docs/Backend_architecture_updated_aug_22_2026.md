# Core Cash: Backend Architecture Document

**Version:** 2.1
**Date:** August 22, 2026
**Audience:** Application Architects, Backend Engineers, DevOps Engineers, Security Teams
**Status:** Ready for Implementation

---

## What Changed in v2.1

| Area | v2.0 | v2.1 | Rationale |
|---|---|---|---|
| **accounts DDL** | Missing `od_limit`, `od_utilised_amount`, `refresh_frequency`, `include_in_cash_position` | All four columns added | Required by Agent 1 confidence logic, cash position calculation, and OD headroom computation |
| **od_headroom** | Not described | Computed field: `od_limit - od_utilised_amount`; never stored, always returned in API response | Avoids stale computed values in DB |
| **decision_log** | Not mentioned | Explicitly deferred to Phase 2; use MongoDB `recommendations` collection for Agent 7 precedent lookup in MVP | Simplifies MVP schema |
| **document version** | 2.0 | 2.1 | Surgical DDL corrections only; no architectural changes |

---

## What Changed in v2.0

This document supersedes v1.0 (July 28, 2026). The fundamental architecture has shifted from a **dual-language stack (ASP.NET Core + Python)** to a **unified Python stack** with two dedicated FastAPI services sharing a common library.

| Area | v1.0 (Previous) | v2.0 (Current) |
|---|---|---|
| **App backend language** | ASP.NET Core (.NET 8) | Python / FastAPI |
| **Shared contract layer** | None (language boundary) | Shared Python lib (Pydantic schemas, types, utils) |
| **Job queue** | ElastiCache Redis | AWS SQS |
| **AI output storage** | PostgreSQL (same DB) | MongoDB (separate, document store) |
| **Inter-service communication** | HTTP (REST calls + Redis) | AWS SQS (async only) |
| **Schema consistency** | Manual sync across language boundary | Single Pydantic library (PyPI package or monorepo) |
| **Deployment** | Two separate runtimes (.NET + Python) | Two Python services, same runtime, independently deployed |
| **Chat protocol** | REST polling | SSE (Server-Sent Events) |

**Why the change:** Eliminating the .NET/Python boundary removes schema drift, halves operational complexity, enables a shared Pydantic type library, and keeps the full team in one language ecosystem. The enterprise sales argument for .NET was evaluated and determined not to outweigh the development velocity cost at this stage.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Technology Stack](#technology-stack)
4. [Dual-Service Python Strategy](#dual-service-python-strategy)
5. [Shared Python Library](#shared-python-library)
6. [AWS Infrastructure](#aws-infrastructure)
7. [App Backend: Python / FastAPI](#app-backend-python--fastapi)
8. [AI Backend: Python / LangGraph](#ai-backend-python--langgraph)
9. [Database Design](#database-design)
10. [Integration Patterns](#integration-patterns)
11. [Security Architecture](#security-architecture)
12. [Monitoring & Observability](#monitoring--observability)
13. [Disaster Recovery & High Availability](#disaster-recovery--high-availability)
14. [Deployment & CI/CD](#deployment--cicd)
15. [Cost Optimization](#cost-optimization)
16. [Implementation Roadmap](#implementation-roadmap)
17. [Appendix: Scripts & Configuration](#appendix-scripts--configuration)

---

## Executive Summary

Core Cash is an **agentic AI treasury decision layer** for enterprise customers in the US financial and banking sector. The backend is a **unified Python dual-service architecture**:

- **App Backend (Python / FastAPI):** Treasury platform layer — auth, file ingestion, cash position, account master, job publishing, result polling, approval workflows, audit logging
- **AI Backend (Python / FastAPI + LangGraph):** Agent orchestration layer — 8 LangGraph agents, Claude Sonnet LLM calls, job consumption, result writing
- **Shared Python Library:** Common Pydantic schemas, types, and utilities shared across both services (PyPI package or monorepo package)
- **AWS SQS:** Decoupled async job queue (app backend publishes, AI backend consumes)
- **PostgreSQL:** Relational store for accounts, entities, transactions (app backend owns)
- **MongoDB:** Document store for agent outputs, audit history, recommendation traces (AI backend owns)

**Key Architectural Principles:**
1. **Unified language** — Both services in Python; one runtime, one team, zero language boundary
2. **Schema-first** — Shared Pydantic lib is the single source of truth for types
3. **Async-first** — SQS decouples job publishing from agent execution; 5-minute latency acceptable
4. **Read-only AI layer** — AI backend reads PostgreSQL (validated cash data only); never writes to it
5. **Separation of stores** — PostgreSQL for ACID-critical treasury data; MongoDB for document-shaped agent outputs
6. **Explainability required** — Every recommendation answers Why/What/When/Control

---

## Architecture Overview

### High-Level Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Next.js Frontend                                 │
│                  REST polling · SSE (chat) · JWT auth                    │
└──────────────┬──────────────────────────────────────┬────────────────────┘
               │ REST / JWT                           │ SSE (chat only)
               │                                      │
┌──────────────▼──────────────────┐   ┌──────────────▼──────────────────┐
│     App Backend · Python/FastAPI │   │   AI Backend · Python/FastAPI   │
│     Treasury platform layer      │   │   LangGraph agent layer         │
│                                  │   │                                 │
│  ┌─────────────┐ ┌────────────┐  │   │  ┌────────────┐ ┌───────────┐  │
│  │ Data ingest │ │Entity/acct │  │   │  │ 8 LangGraph│ │Claude 3.5 │  │
│  │ File parsers│ │management  │  │   │  │ agents     │ │Sonnet LLM │  │
│  └─────────────┘ └────────────┘  │   │  └────────────┘ └───────────┘  │
│  ┌──────────────────────────────┐ │   │  ┌─────────────────────────┐   │
│  │ Job publisher · Poll endpts  │ │   │  │ Job consumer · Result   │   │
│  └──────────────────────────────┘ │   │  │ writer                  │   │
│                                  │   │  └─────────────────────────┘   │
│         ┌────────────────┐        │   └────────────────┬────────────────┘
│         │ Shared Python  │        │                    │
│         │ lib (Pydantic  ◄────────┼────────────────────┘
│         │ schemas/types) │        │
│         └────────────────┘        │
└──────────────┬───────────────────┘
               │ publish job                     consume job
               │                                      │
               └──────────────┬───────────────────────┘
                              │
                    ┌─────────▼────────┐
                    │    AWS SQS       │
                    │  Agent job queue │
                    └─────────┬────────┘
                              │
          ┌───────────────────┼────────────────────┐
          │                   │                    │
┌─────────▼──────────┐        │          ┌────────▼──────────┐
│    PostgreSQL       │        │          │     MongoDB        │
│  (RDS Aurora)      │◄───────┘          │  (DocumentDB /    │
│                    │  read-only        │   Atlas)           │
│ Accounts · entities│  (validated       │                    │
│ transactions       │   cash data)      │ Agent outputs      │
│                    │                   │ Audit · history    │
└────────────────────┘                   └───────────────────-┘

     ┌──────────────┐   ┌───────────────┐   ┌─────────────────┐
     │  Bank files  │   │  ERP / TMS    │   │  Anthropic API  │
     │ BAI2·camt·CSV│   │ AR·AP extracts│   │  Claude 3.5 Son │
     └──────────────┘   └───────────────┘   └─────────────────┘
```

### Data Flow

```
File Ingestion Flow:
  Frontend → POST /api/files/upload
    ↓
  App Backend validates, stores raw file in S3
    ↓
  App Backend parses (BAI2/camt/CSV)
    ↓
  Parsed data written to PostgreSQL (normalized cash model)
    ↓
  App Backend publishes job to SQS → AI Backend consumes (if triggered)

Recommendation Flow:
  Frontend → POST /api/recommendations/request
    ↓
  App Backend validates, creates recommendation record (status: pending)
    ↓
  App Backend publishes job message to SQS
    ↓
  Returns { request_id, status: "queued" } to Frontend (202 Accepted)
    ↓
  Frontend polls: GET /api/recommendations/{request_id} every 5s
    ↓
  [Async] AI Backend dequeues job from SQS
    ↓
  AI Backend reads cash position from PostgreSQL (read-only, validated data)
    ↓
  AI Backend runs 8-agent LangGraph chain (30s–5min acceptable)
    ↓
  AI Backend writes recommendation + reasoning trace to MongoDB
    ↓
  App Backend poll endpoint reads from MongoDB → returns to Frontend
    ↓
  Frontend shows recommendation; user clicks Approve
    ↓
  Frontend → POST /api/recommendations/{id}/approve
    ↓
  App Backend records approval in PostgreSQL (audit trail)
    ↓
  App Backend updates recommendation status in MongoDB

Chat Flow:
  Frontend opens SSE stream → GET /ai/chat/stream
    ↓
  AI Backend handles SSE; calls Claude for streaming response
    ↓
  Tokens streamed back to Frontend in real-time
```

---

## Technology Stack

### Backend Services

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| **App Backend Framework** | Python / FastAPI | 3.11 / 0.104+ | RESTful API, treasury platform |
| **AI Backend Framework** | Python / FastAPI | 3.11 / 0.104+ | Agent orchestration, SSE chat |
| **Shared Library** | Pydantic v2 | 2.5+ | Schemas, types, utils (shared package) |
| **Agent Orchestration** | LangGraph | Latest | 8-agent state machine |
| **LLM** | Claude 3.5 Sonnet | claude-sonnet-4-6 | Recommendations, summaries |
| **App DB ORM** | SQLAlchemy | 2.0+ | PostgreSQL access (async) |
| **AI DB Client** | Motor (async) | 3.3+ | MongoDB async driver |
| **Job Queue** | AWS SQS | AWS-managed | Async job decoupling |
| **File Storage** | AWS S3 | AWS-managed | Raw file uploads, exports |
| **Auth** | AWS Cognito + OIDC | AWS-managed | JWT tokens, roles |
| **Secrets** | AWS Secrets Manager | AWS-managed | DB credentials, API keys |
| **Logging** | structlog | Latest | Structured JSON logging |
| **Validation** | Pydantic v2 | 2.5+ | Request/response validation |
| **HTTP Client** | httpx | 0.25+ | Inter-service, Anthropic API |

### AWS Services

| Service | Purpose | Sizing |
|---|---|---|
| **ECS Fargate** | Container orchestration (App + AI services) | App: 512 CPU/1024 MB; AI: 1024 CPU/2048 MB |
| **RDS Aurora PostgreSQL** | Relational treasury data | db.t4g.medium, 100 GB, Multi-AZ |
| **DocumentDB / MongoDB Atlas** | Agent outputs + audit history | db.t3.medium or Atlas M10 cluster |
| **AWS SQS** | Async job queue (App → AI) | Standard queue, 5-min visibility timeout |
| **S3** | Raw file storage + exports | Versioning, AES-256, lifecycle |
| **ALB** | Load balancer (App + AI) | HTTPS, path-based routing |
| **Cognito** | User identity + JWT issuance | User Pool + App Client |
| **Secrets Manager** | DB passwords, LLM keys | Auto-rotation every 90 days |
| **CloudWatch** | Logs, metrics, alarms | 30-day retention |
| **ECR** | Container registry | core-cash-app, core-cash-ai |
| **Route 53** | DNS | Per-customer subdomain |
| **ACM** | TLS certificates | Managed, free |

---

## Dual-Service Python Strategy

### Why Two Python Services, Not One?

Separating the **App Backend** from the **AI Backend** preserves independent scalability, deployability, and fault isolation — but without the language-boundary overhead of .NET + Python.

```
One Codebase (monorepo or two repos):
  core-cash/
  ├── shared/          ← Pydantic schemas, types, enums, utils (pip install -e .)
  ├── app-backend/     ← FastAPI: treasury ops, file ingestion, job publishing
  └── ai-backend/      ← FastAPI: LangGraph agents, LLM calls, job consumption
```

### Responsibility Boundary

#### App Backend Owns
```
✓ User authentication (JWT validation from Cognito)
✓ Role-based access control (CFO, TreasuryManager, Analyst, Viewer)
✓ File upload, validation, and parsing (BAI2, camt.053, MT940, CSV)
✓ Cash data write path (PostgreSQL — accounts, entities, statements, transactions)
✓ Account master CRUD
✓ AR/AP schedule management
✓ Job publishing to SQS (triggers AI agents)
✓ Result polling endpoints (reads from MongoDB)
✓ Approval workflow (reads/writes approval status)
✓ Audit logging (every action to PostgreSQL audit_log table)
✓ Policy enforcement rules
✓ REST API for all frontend interactions (except SSE chat)
```

#### AI Backend Owns
```
✓ SQS job consumption (dequeues recommendation/forecast jobs)
✓ 8-agent LangGraph chain orchestration
✓ PostgreSQL read access (validated cash data only — never writes)
✓ Claude 3.5 Sonnet LLM calls via Anthropic API
✓ Recommendation generation (Why/What/When/Control)
✓ Variance explanation, CFO summary, pattern detection
✓ Reasoning trace logging
✓ Result writing to MongoDB (recommendations, audit history, agent outputs)
✓ SSE streaming for chat panel (frontend chat only)
```

#### Shared Python Library Owns
```
✓ All Pydantic request/response schemas (imported by both services)
✓ Domain types and enums (Currency, RiskLevel, RecommendationStatus, etc.)
✓ Utility functions (date math, currency conversion, formatting)
✓ SQS message envelope schema (JobMessage, JobResult)
✓ Error codes and standard error response shapes
```

### Why SQS Instead of Redis?

| Factor | Redis (v1.0) | SQS (v2.0) |
|---|---|---|
| **Durability** | In-memory (data lost on restart) | Durable (persisted, replicated) |
| **Delivery guarantee** | At-most-once | At-least-once |
| **Visibility timeout** | Manual (RPOP = destructive) | Built-in (message hidden during processing) |
| **Dead-letter queue** | Must build manually | Native DLQ support |
| **Monitoring** | Custom metrics | Native CloudWatch metrics |
| **Ops overhead** | Manage Redis cluster | Fully managed (no cluster) |
| **Cost** | $30–40/month per customer | ~$0.40 per million messages (~$1–5/month) |
| **5-min latency OK?** | Yes | Yes |

SQS is cheaper, more durable, has native DLQ, and requires zero ops overhead. Redis is no longer needed for the job queue; it can be removed or retained for optional caching only.

### Why MongoDB for AI Outputs?

PostgreSQL is the right store for structured, relational treasury data (accounts, statements, transactions) where ACID guarantees matter. MongoDB is the right store for agent outputs because:

- **Agent outputs are document-shaped** — Recommendation JSON varies per agent, per run; hard to schema in SQL
- **Reasoning traces are deeply nested** — Array of agent steps, each with sub-fields
- **Audit history is append-only** — No complex relational queries needed
- **No foreign keys needed** — Agent outputs reference PostgreSQL IDs by value, not enforced FK
- **Fast reads by request_id** — MongoDB's document lookup is fast and simple for polling

```
PostgreSQL owns (relational, ACID):
  accounts, legal_entities, banks, statements, transactions,
  source_files, ar_schedule, ap_schedule, approvals, audit_log, policies

MongoDB owns (document, append-only):
  recommendations (full JSON, reasoning trace, confidence)
  agent_run_history (per-agent step logs)
  cfosummary_outputs (narrative text + metadata)
  daily_briefings (prose content)
  pattern_signals (trend/anomaly detection results)
```

---

## Shared Python Library

### Structure

```
core-cash-shared/
├── pyproject.toml             ← pip installable (or editable install)
├── core_cash_shared/
│   ├── __init__.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── cash.py            ← CashPosition, Account, Statement, Transaction
│   │   ├── recommendation.py  ← Recommendation, Why/What/When/Control, Alternatives
│   │   ├── forecast.py        ← ForecastResult, ForecastHorizon, Assumptions
│   │   ├── risk.py            ← LiquidityRisk, RiskLevel, RiskType
│   │   ├── jobs.py            ← SQSJobMessage, SQSJobResult (job envelope schemas)
│   │   ├── auth.py            ← UserClaims, Role, TokenPayload
│   │   └── errors.py          ← StandardError, ErrorCode
│   ├── types/
│   │   ├── __init__.py
│   │   ├── enums.py           ← Currency, RiskLevel, RecommendationStatus, AgentName
│   │   └── aliases.py         ← ClientId, EntityId, AccountId (type aliases)
│   └── utils/
│       ├── __init__.py
│       ├── dates.py           ← business_days_between, next_bank_cutoff
│       ├── currency.py        ← convert_to_usd, format_amount
│       └── validation.py      ← validate_account_number, validate_currency
```

### Key Schemas

```python
# core_cash_shared/schemas/recommendation.py
from pydantic import BaseModel, Field
from typing import Optional, List
from core_cash_shared.types.enums import RecommendationStatus

class Control(BaseModel):
    policy_check: str                     # "pass" | "fail" | "warning"
    restricted_accounts_clear: bool
    requires_approval: bool
    approval_owner: str                   # "TreasuryManager" | "CFO"

class Recommendation(BaseModel):
    why: str = Field(..., description="Root cause and drivers")
    what: str = Field(..., description="Specific action to take")
    when: str = Field(..., description="Timing and bank cut-off")
    control: Control
    alternatives: Optional[List[str]] = None
    confidence: float = Field(..., ge=0.0, le=1.0)

class RecommendationDocument(BaseModel):
    """Written to MongoDB by AI backend; read by App backend"""
    request_id: str
    client_id: str
    recommendation: Recommendation
    reasoning_trace: List[dict]
    status: RecommendationStatus
    created_at: str
    completed_at: Optional[str] = None


# core_cash_shared/schemas/jobs.py
from pydantic import BaseModel
from typing import Any, Optional

class SQSJobMessage(BaseModel):
    """Published by App backend; consumed by AI backend"""
    job_id: str
    job_type: str                          # "recommendation" | "forecast" | "cfosummary"
    client_id: str
    payload: dict                          # Job-specific data (cash position, policy_id, etc.)
    published_at: str
    correlation_id: Optional[str] = None  # For tracing

class SQSJobResult(BaseModel):
    """Written to MongoDB; polled via App backend"""
    job_id: str
    status: str                            # "pending" | "running" | "completed" | "failed"
    result: Optional[dict] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None
```

### Installation in Both Services

```toml
# app-backend/pyproject.toml
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.104"
sqlalchemy = "^2.0"
boto3 = "^1.28"                    # SQS publish
core-cash-shared = { path = "../shared", develop = true }  # monorepo

# ai-backend/pyproject.toml
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.104"
langgraph = "^0.0.1"
anthropic = "^0.7"
motor = "^3.3"                     # MongoDB async
boto3 = "^1.28"                    # SQS consume
core-cash-shared = { path = "../shared", develop = true }  # monorepo
```

---

## AWS Infrastructure

### VPC & Networking

```yaml
VPC: 10.0.0.0/16

Public Subnets (ALB):
  us-east-1a: 10.0.0.0/24
  us-east-1b: 10.0.1.0/24

Private Subnets (ECS):
  us-east-1a: 10.0.10.0/24
  us-east-1b: 10.0.11.0/24

Private Subnets (Databases):
  us-east-1a: 10.0.20.0/24
  us-east-1b: 10.0.21.0/24

NAT Gateways: 1 per AZ
Internet Gateway: Attached to VPC
```

### AWS SQS (Job Queue)

```yaml
Queue Name: core-cash-agent-jobs-{customer}
Type: Standard (at-least-once delivery)
Visibility Timeout: 300s (5 min — covers max agent run time)
Message Retention: 4 days (messages expire if not consumed)
Dead-Letter Queue: core-cash-agent-jobs-dlq-{customer}
  - Max Receive Count: 3 (retry 3× before moving to DLQ)
  - DLQ Retention: 14 days (for debugging)

Permissions:
  App Backend ECS Task Role: sqs:SendMessage
  AI Backend ECS Task Role: sqs:ReceiveMessage, sqs:DeleteMessage, sqs:GetQueueAttributes
```

**Terraform:**
```hcl
resource "aws_sqs_queue" "agent_jobs_dlq" {
  name                      = "core-cash-agent-jobs-dlq"
  message_retention_seconds = 1209600   # 14 days
  tags                      = { Name = "core-cash-agent-jobs-dlq" }
}

resource "aws_sqs_queue" "agent_jobs" {
  name                       = "core-cash-agent-jobs"
  visibility_timeout_seconds = 300       # 5 min (max agent run)
  message_retention_seconds  = 345600    # 4 days
  receive_wait_time_seconds  = 20        # Long polling (reduce empty receives)

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.agent_jobs_dlq.arn
    maxReceiveCount     = 3
  })

  tags = { Name = "core-cash-agent-jobs" }
}
```

**App Backend publishes:**
```python
# app-backend/app/services/job_publisher.py
import boto3
import json
from core_cash_shared.schemas.jobs import SQSJobMessage
from app.config import settings

sqs = boto3.client("sqs", region_name=settings.AWS_REGION)

async def publish_recommendation_job(
    job_id: str,
    client_id: str,
    cash_position_date: str,
    policy_id: str
) -> bool:
    message = SQSJobMessage(
        job_id=job_id,
        job_type="recommendation",
        client_id=client_id,
        payload={
            "cash_position_date": cash_position_date,
            "policy_id": policy_id
        },
        published_at=datetime.utcnow().isoformat()
    )

    try:
        response = sqs.send_message(
            QueueUrl=settings.SQS_QUEUE_URL,
            MessageBody=message.model_dump_json(),
            MessageAttributes={
                "job_type": {
                    "StringValue": "recommendation",
                    "DataType": "String"
                }
            }
        )
        return True
    except Exception as e:
        logger.error(f"Failed to publish job {job_id}: {e}")
        return False
```

**AI Backend consumes:**
```python
# ai-backend/app/worker/job_consumer.py
import boto3
import json
import asyncio
from core_cash_shared.schemas.jobs import SQSJobMessage
from app.agents.orchestrator import AgentOrchestrator
from app.config import settings

sqs = boto3.client("sqs", region_name=settings.AWS_REGION)

async def consume_jobs():
    """Long-running consumer — runs as background task on AI backend startup"""
    orchestrator = AgentOrchestrator()

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=settings.SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,           # Long polling
                VisibilityTimeout=300,        # 5 min processing window
                MessageAttributeNames=["All"]
            )

            messages = response.get("Messages", [])
            if not messages:
                continue

            for msg in messages:
                job = SQSJobMessage.model_validate_json(msg["Body"])

                try:
                    await orchestrator.run(job)
                    # Delete message only on success
                    sqs.delete_message(
                        QueueUrl=settings.SQS_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )
                except Exception as e:
                    logger.error(f"Job {job.job_id} failed: {e}")
                    # Don't delete — let visibility timeout expire → retry → DLQ

        except Exception as e:
            logger.error(f"Consumer error: {e}")
            await asyncio.sleep(5)
```

### RDS Aurora PostgreSQL

```yaml
Engine: Aurora PostgreSQL 15.3
Instance: db.t4g.medium (2 vCPU, 4 GB RAM)
Storage: 100 GB gp3, Multi-AZ
Backup Retention: 35 days
Encryption: KMS
Owned By: App Backend (read/write)
AI Backend Access: Read-only IAM user, separate credentials
```

### MongoDB (DocumentDB or Atlas)

```yaml
Option A - AWS DocumentDB:
  Engine: DocumentDB 5.0 (MongoDB-compatible)
  Instance: db.t3.medium
  Cluster: 1 primary + 1 replica (Multi-AZ)
  Encryption: KMS at rest, TLS in transit
  Backup: 35 days

Option B - MongoDB Atlas (Recommended for MVP):
  Tier: M10 (2 vCPU, 2 GB RAM)
  Region: us-east-1
  Multi-AZ: Yes (3-node replica set)
  Backup: Continuous, 35 days
  Cost: ~$57/month vs ~$200/month DocumentDB
  Note: Atlas VPC peering with AWS VPC required

Owned By: AI Backend (read/write)
App Backend Access: Read-only (for polling recommendation status)

Collections:
  recommendations     ← Agent recommendation outputs
  agent_run_history   ← Per-step agent trace logs
  cfo_summaries       ← Narrative report outputs
  daily_briefings     ← Prose briefing content
  pattern_signals     ← Trend/anomaly detection results
```

### ECS Fargate — App Backend

```yaml
Task Definition:
  Image: ECR core-cash-app:latest
  CPU: 512 (0.5 vCPU)
  Memory: 1024 MB
  Port: 8000
  Environment:
    DATABASE_URL: postgresql+asyncpg://...  (from Secrets Manager)
    MONGODB_URI: mongodb+srv://...          (from Secrets Manager)
    SQS_QUEUE_URL: https://sqs.us-east-1...
    COGNITO_POOL_ID: us-east-1_xxxxxxxxx
    AWS_REGION: us-east-1
  Health Check: GET /health

Service:
  Desired Count: 2 (Multi-AZ HA)
  Auto-scale: 2–6 tasks, target 70% CPU
  Load Balancer: ALB, path /api/* and /auth/*
```

### ECS Fargate — AI Backend

```yaml
Task Definition:
  Image: ECR core-cash-ai:latest
  CPU: 1024 (1 vCPU)
  Memory: 2048 MB
  Port: 8001
  Environment:
    MONGODB_URI: mongodb+srv://...          (from Secrets Manager)
    POSTGRES_READONLY_URL: postgresql+asyncpg://...  (from Secrets Manager)
    ANTHROPIC_API_KEY: sk-ant-...           (from Secrets Manager)
    SQS_QUEUE_URL: https://sqs.us-east-1...
    AWS_REGION: us-east-1
  Health Check: GET /health

Service:
  Desired Count: 2
  Auto-scale: 2–4 tasks, target 60% CPU
  Load Balancer: ALB, path /agents/* and /ai/*
```

---

## App Backend: Python / FastAPI

### Project Structure

```
app-backend/
├── app/
│   ├── main.py                    # FastAPI entry point, lifespan, routes
│   ├── config.py                  # Settings (env vars, Secrets Manager)
│   ├── database.py                # SQLAlchemy async engine
│   ├── mongo.py                   # Motor client (read-only polling)
│   ├── dependencies.py            # get_db, get_current_user, require_role
│   ├── models/                    # SQLAlchemy ORM models (PostgreSQL)
│   │   ├── client.py
│   │   ├── entity.py
│   │   ├── bank.py
│   │   ├── account.py
│   │   ├── statement.py
│   │   ├── transaction.py
│   │   ├── source_file.py
│   │   ├── recommendation_ref.py  # Thin ref table: (request_id, status, client_id)
│   │   ├── approval.py
│   │   └── audit_log.py
│   ├── routes/
│   │   ├── auth.py                # /auth/login, /auth/me, /auth/refresh
│   │   ├── cash_position.py       # /api/cash-position/*
│   │   ├── files.py               # /api/files/*
│   │   ├── recommendations.py     # /api/recommendations/*
│   │   ├── accounts.py            # /api/accounts/*
│   │   ├── forecast.py            # /api/forecast/*
│   │   ├── liquidity_risk.py      # /api/liquidity-risk/*
│   │   ├── audit.py               # /api/audit-log/*
│   │   └── health.py              # /health
│   ├── services/
│   │   ├── cash_position_service.py
│   │   ├── file_ingestion_service.py
│   │   ├── recommendation_service.py  # Publishes to SQS, polls MongoDB
│   │   ├── forecast_service.py
│   │   ├── audit_service.py
│   │   ├── s3_service.py
│   │   └── job_publisher.py       # SQS publish
│   ├── parsers/
│   │   ├── csv_parser.py
│   │   ├── bai2_parser.py
│   │   ├── camt053_parser.py
│   │   └── mt940_parser.py
│   └── middleware/
│       ├── audit_middleware.py    # Logs every request to audit_log
│       └── error_middleware.py
├── alembic/                       # DB migrations
├── tests/
├── Dockerfile
├── pyproject.toml
└── .env.example
```

### app/main.py

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.config import settings
from app.database import engine, Base
from app.mongo import init_mongo, close_mongo
from app.middleware.audit_middleware import AuditMiddleware
from app.middleware.error_middleware import ErrorHandlingMiddleware
from app.routes import auth, cash_position, files, recommendations, accounts, health

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_backend.startup", environment=settings.ENVIRONMENT)

    # Initialize databases
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await init_mongo()

    yield

    await close_mongo()
    await engine.dispose()
    logger.info("app_backend.shutdown")


app = FastAPI(
    title="Core Cash App Backend",
    description="Treasury platform layer — file ingestion, cash position, approvals",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.add_middleware(AuditMiddleware)
app.add_middleware(ErrorHandlingMiddleware)

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth")
app.include_router(cash_position.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(recommendations.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
```

### app/services/recommendation_service.py

```python
import uuid
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy.ext.asyncio import AsyncSession
from core_cash_shared.schemas.recommendation import RecommendationDocument
from core_cash_shared.schemas.jobs import SQSJobMessage
from app.models.recommendation_ref import RecommendationRef
from app.services.job_publisher import publish_job
import structlog

logger = structlog.get_logger()


class RecommendationService:

    def __init__(self, db: AsyncSession, mongo: AsyncIOMotorClient):
        self.db = db
        self.mongo = mongo
        self.collection = mongo["core_cash"]["recommendations"]

    async def request_recommendation(
        self, client_id: str, cash_position_date: str, policy_id: str
    ) -> dict:
        job_id = f"rec_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        # Write thin reference row to PostgreSQL (for approval workflow)
        ref = RecommendationRef(
            job_id=job_id,
            client_id=client_id,
            status="pending",
            created_at=datetime.utcnow()
        )
        self.db.add(ref)
        await self.db.commit()

        # Write pending document to MongoDB (AI backend will update it)
        await self.collection.insert_one({
            "job_id": job_id,
            "client_id": client_id,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        })

        # Publish job to SQS
        job = SQSJobMessage(
            job_id=job_id,
            job_type="recommendation",
            client_id=client_id,
            payload={
                "cash_position_date": cash_position_date,
                "policy_id": policy_id
            },
            published_at=datetime.utcnow().isoformat()
        )
        await publish_job(job)

        logger.info("recommendation.queued", job_id=job_id, client_id=client_id)

        return {
            "request_id": job_id,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "estimated_completion": "30–60 seconds"
        }

    async def get_recommendation(self, client_id: str, job_id: str) -> dict | None:
        doc = await self.collection.find_one({
            "job_id": job_id,
            "client_id": client_id
        })
        if not doc:
            return None
        doc.pop("_id", None)   # Remove MongoDB internal ID before returning
        return doc

    async def approve_recommendation(
        self, client_id: str, job_id: str, user_id: str, comment: str | None
    ) -> dict:
        # Update MongoDB status
        await self.collection.update_one(
            {"job_id": job_id, "client_id": client_id},
            {"$set": {"status": "approved", "approved_by": user_id, "approved_at": datetime.utcnow().isoformat()}}
        )

        # Update PostgreSQL reference + create approval record
        from app.models.approval import Approval
        approval = Approval(
            job_id=job_id,
            client_id=client_id,
            user_id=user_id,
            action="approve",
            comment=comment,
            created_at=datetime.utcnow()
        )
        self.db.add(approval)
        await self.db.commit()

        return {"status": "approved", "approved_by": user_id}
```

---

## AI Backend: Python / LangGraph

### Project Structure

```
ai-backend/
├── app/
│   ├── main.py                    # FastAPI entry point, lifespan, SSE routes
│   ├── config.py                  # Settings
│   ├── mongo.py                   # Motor client (read/write)
│   ├── postgres_readonly.py       # SQLAlchemy read-only connection to PostgreSQL
│   ├── worker/
│   │   ├── job_consumer.py        # SQS polling loop (background task)
│   │   └── result_writer.py       # Writes agent outputs to MongoDB
│   ├── agents/
│   │   ├── orchestrator.py        # LangGraph state machine, runs all 8 agents
│   │   ├── daily_cash_agent.py    # Agent 1: Query cash position
│   │   ├── forecast_agent.py      # Agent 2: 7/30/60-day forecast
│   │   ├── liquidity_risk_agent.py # Agent 3: Risk scoring
│   │   ├── recommendation_agent.py # Agent 4: Why/What/When/Control
│   │   ├── variance_agent.py      # Agent 5: Variance explanation
│   │   ├── cfosummary_agent.py    # Agent 6: Narrative composition
│   │   ├── continuity_agent.py    # Agent 7: Precedent lookup
│   │   └── policy_agent.py        # Agent 8: Policy checks
│   ├── llm/
│   │   ├── client.py              # Anthropic client wrapper
│   │   └── prompts/               # System prompts per agent
│   ├── routes/
│   │   ├── health.py              # /health
│   │   └── chat.py                # /ai/chat/stream (SSE)
│   └── services/
│       └── cash_data_service.py   # Reads PostgreSQL (validated cash data)
├── tests/
├── Dockerfile
├── pyproject.toml
└── .env.example
```

### app/agents/orchestrator.py

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
from core_cash_shared.schemas.jobs import SQSJobMessage
from app.agents.daily_cash_agent import DailyCashAgent
from app.agents.liquidity_risk_agent import LiquidityRiskAgent
from app.agents.forecast_agent import ForecastAgent
from app.agents.recommendation_agent import RecommendationAgent
from app.agents.variance_agent import VarianceAgent
from app.agents.cfosummary_agent import CFOSummaryAgent
from app.agents.policy_agent import PolicyAgent
from app.worker.result_writer import ResultWriter
import structlog

logger = structlog.get_logger()


class AgentState(TypedDict):
    job: SQSJobMessage
    cash_position: Optional[dict]
    liquidity_risks: Optional[list]
    forecast: Optional[dict]
    recommendation: Optional[dict]
    variance: Optional[dict]
    policy_check: Optional[dict]
    cfo_summary: Optional[str]
    errors: list


class AgentOrchestrator:

    def __init__(self):
        self.graph = self._build_graph()
        self.result_writer = ResultWriter()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)

        # Register nodes (each agent is a node)
        graph.add_node("daily_cash", DailyCashAgent().run)
        graph.add_node("liquidity_risk", LiquidityRiskAgent().run)
        graph.add_node("forecast", ForecastAgent().run)
        graph.add_node("policy_check", PolicyAgent().run)
        graph.add_node("recommendation", RecommendationAgent().run)
        graph.add_node("variance", VarianceAgent().run)
        graph.add_node("cfo_summary", CFOSummaryAgent().run)

        # Define execution order
        graph.set_entry_point("daily_cash")
        graph.add_edge("daily_cash", "liquidity_risk")
        graph.add_edge("liquidity_risk", "forecast")
        graph.add_edge("forecast", "policy_check")
        graph.add_edge("policy_check", "recommendation")
        graph.add_edge("recommendation", "variance")
        graph.add_edge("variance", "cfo_summary")
        graph.add_edge("cfo_summary", END)

        return graph.compile()

    async def run(self, job: SQSJobMessage) -> None:
        logger.info("orchestrator.start", job_id=job.job_id, job_type=job.job_type)

        initial_state: AgentState = {
            "job": job,
            "cash_position": None,
            "liquidity_risks": None,
            "forecast": None,
            "recommendation": None,
            "variance": None,
            "policy_check": None,
            "cfo_summary": None,
            "errors": []
        }

        try:
            final_state = await self.graph.ainvoke(initial_state)
            await self.result_writer.write_recommendation(job.job_id, job.client_id, final_state)
            logger.info("orchestrator.complete", job_id=job.job_id)

        except Exception as e:
            logger.error("orchestrator.failed", job_id=job.job_id, error=str(e))
            await self.result_writer.write_failure(job.job_id, job.client_id, str(e))
            raise
```

### app/agents/recommendation_agent.py

```python
from anthropic import AsyncAnthropic
from core_cash_shared.schemas.recommendation import Recommendation, Control
from app.config import settings
import structlog
import json

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are a treasury AI assistant generating actionable cash management recommendations.

Every recommendation MUST include exactly these four fields:
1. WHY: The specific drivers (payroll, AR delay, tax payment, FX move, bank fee, etc.)
2. WHAT: The specific action (transfer, sweep, accelerate collection, defer payment, etc.)
3. WHEN: Exact timing — include bank cut-off times and value dates
4. CONTROL: Policy checks, restricted account clearance, and required approval role

Respond ONLY with valid JSON matching this exact schema:
{
  "why": "string",
  "what": "string",
  "when": "string",
  "control": {
    "policy_check": "pass|fail|warning",
    "restricted_accounts_clear": true|false,
    "requires_approval": true|false,
    "approval_owner": "TreasuryManager|CFO"
  },
  "alternatives": ["string", "string"],
  "confidence": 0.0
}"""


class RecommendationAgent:

    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def run(self, state: dict) -> dict:
        cash_position = state["cash_position"]
        risks = state["liquidity_risks"]
        forecast = state["forecast"]
        policy = state["policy_check"]

        context = self._build_context(cash_position, risks, forecast, policy)

        response = await self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}]
        )

        raw = response.content[0].text
        try:
            rec_dict = json.loads(raw)
            recommendation = Recommendation(**rec_dict)
            logger.info("recommendation_agent.complete",
                        confidence=recommendation.confidence)
            state["recommendation"] = recommendation.model_dump()
        except (json.JSONDecodeError, Exception) as e:
            logger.error("recommendation_agent.parse_error", error=str(e))
            state["errors"].append(f"recommendation_agent: {e}")

        return state

    def _build_context(self, cash_position, risks, forecast, policy) -> str:
        risk_summary = "\n".join([
            f"  - [{r['severity']}] {r['message']}"
            for r in (risks or [])
        ])
        return f"""
Current Cash Position:
  Total USD: ${cash_position.get('total_usd', 0):,.2f}
  As of: {cash_position.get('as_of_date')}

Active Liquidity Risks:
{risk_summary or '  None detected'}

7-Day Forecast:
  Projected balance day 7: ${forecast.get('day_7_balance', 0):,.2f}
  Key drivers: {forecast.get('key_drivers', 'N/A')}

Policy Status:
  Min threshold: ${policy.get('min_threshold_usd', 0):,.2f}
  Policy check: {policy.get('status', 'unknown')}

Generate a treasury recommendation based on the above context.
"""
```

### Dockerfile (Shared for Both Services)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

# Install shared library first (layer cache optimization)
COPY shared/ /shared/
RUN pip install --no-cache-dir -e /shared/

# Install service dependencies
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --no-dev

# Copy service code
COPY app/ ./app/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Database Design

### PostgreSQL Schema (App Backend — Read/Write)

```sql
-- Clients
CREATE TABLE clients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Legal Entities
CREATE TABLE legal_entities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL REFERENCES clients(id),
  name VARCHAR(255) NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  country CHAR(2) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(client_id, name)
);

-- Banks
CREATE TABLE banks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL REFERENCES clients(id),
  name VARCHAR(255) NOT NULL,
  swift_code VARCHAR(11),
  country CHAR(2) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Accounts
-- Note: od_headroom is NOT stored — always computed as (od_limit - od_utilised_amount)
-- and returned in API responses by the App Backend service layer.
CREATE TABLE accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL REFERENCES clients(id),
  bank_id UUID NOT NULL REFERENCES banks(id),
  entity_id UUID NOT NULL REFERENCES legal_entities(id),
  account_number VARCHAR(50) NOT NULL,
  account_name VARCHAR(255),
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  account_type VARCHAR(50),
  min_threshold NUMERIC(15,2),
  is_restricted BOOLEAN DEFAULT FALSE,
  od_limit NUMERIC(15,2) DEFAULT NULL,             -- Overdraft facility limit; NULL if no OD arrangement
  od_utilised_amount NUMERIC(15,2) DEFAULT NULL,   -- Amount of OD currently drawn; NULL if no OD
  refresh_frequency VARCHAR(20) NOT NULL DEFAULT 'Daily',   -- Daily | Weekly | Monthly
  include_in_cash_position BOOLEAN NOT NULL DEFAULT TRUE,   -- FALSE for restricted/petty cash accounts
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(client_id, bank_id, account_number)
);

-- Statements (daily ending balances)
CREATE TABLE statements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES accounts(id),
  statement_date DATE NOT NULL,
  opening_balance NUMERIC(15,2),
  closing_balance NUMERIC(15,2) NOT NULL,
  available_balance NUMERIC(15,2),
  current_balance NUMERIC(15,2),
  source_file_id UUID,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(account_id, statement_date)
);

-- Transactions
CREATE TABLE transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES accounts(id),
  statement_id UUID REFERENCES statements(id),
  transaction_date DATE NOT NULL,
  value_date DATE,
  amount NUMERIC(15,2) NOT NULL,
  debit_credit CHAR(1) NOT NULL,
  description VARCHAR(500),
  counterparty VARCHAR(255),
  reference VARCHAR(255),
  bank_code VARCHAR(20),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Source Files (upload audit trail)
CREATE TABLE source_files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL REFERENCES clients(id),
  s3_key VARCHAR(500) NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  file_type VARCHAR(20),
  rows_processed INTEGER,
  rows_skipped INTEGER,
  status VARCHAR(50),
  error_message TEXT,
  uploaded_by VARCHAR(255),
  uploaded_at TIMESTAMP DEFAULT NOW(),
  parsed_at TIMESTAMP
);

-- Recommendation References (thin table — full doc in MongoDB)
CREATE TABLE recommendation_refs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id VARCHAR(100) NOT NULL UNIQUE,
  client_id UUID NOT NULL REFERENCES clients(id),
  status VARCHAR(50) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_rec_job_id ON recommendation_refs(job_id);
CREATE INDEX idx_rec_client_status ON recommendation_refs(client_id, status);

-- Approvals (audit trail)
CREATE TABLE approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id VARCHAR(100) NOT NULL,
  client_id UUID NOT NULL REFERENCES clients(id),
  user_id VARCHAR(255) NOT NULL,
  action VARCHAR(50) NOT NULL,
  comment TEXT,
  ip_address VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Decision Log: DEFERRED TO PHASE 2
-- MVP uses the MongoDB `recommendations` collection for Agent 7 (Treasury Continuity)
-- precedent lookup. A structured decision_log table with full decision context,
-- cross-recommendation linking, and outcome tracking is planned for Phase 2.

-- Audit Log (immutable, every action)
CREATE TABLE audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL,
  user_id VARCHAR(255),
  action VARCHAR(100) NOT NULL,
  entity_type VARCHAR(50),
  entity_id VARCHAR(100),
  old_value JSONB,
  new_value JSONB,
  ip_address VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);

-- AR / AP Schedules
CREATE TABLE ar_schedule (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL REFERENCES clients(id),
  entity_id UUID NOT NULL REFERENCES legal_entities(id),
  customer_name VARCHAR(255),
  amount NUMERIC(15,2) NOT NULL,
  expected_date DATE NOT NULL,
  description VARCHAR(500),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE ap_schedule (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL REFERENCES clients(id),
  entity_id UUID NOT NULL REFERENCES legal_entities(id),
  vendor_name VARCHAR(255),
  amount NUMERIC(15,2) NOT NULL,
  due_date DATE NOT NULL,
  description VARCHAR(500),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Performance Indexes
CREATE INDEX idx_statements_account_date ON statements(account_id, statement_date DESC);
CREATE INDEX idx_transactions_account_date ON transactions(account_id, transaction_date DESC);
CREATE INDEX idx_audit_log_client_date ON audit_log(client_id, created_at DESC);
CREATE INDEX idx_ar_client_date ON ar_schedule(client_id, expected_date);
CREATE INDEX idx_ap_client_date ON ap_schedule(client_id, due_date);
```

### MongoDB Collections (AI Backend — Read/Write)

```javascript
// recommendations collection
{
  "_id": ObjectId("..."),
  "job_id": "rec_20260822_001_a1b2c3d4",
  "client_id": "uuid-client",
  "status": "completed",              // pending | running | completed | failed | approved | rejected
  "recommendation": {
    "why": "Payroll $2M due Friday; forecast shows $1.8M shortfall",
    "what": "Transfer $2.2M from UK entity to US HQ",
    "when": "Thursday 3 PM ET (before 4 PM cut-off); value date Friday",
    "control": {
      "policy_check": "pass",
      "restricted_accounts_clear": true,
      "requires_approval": true,
      "approval_owner": "TreasuryManager"
    },
    "alternatives": [
      "Borrow short-term against AR ($50K interest risk)",
      "Delay payroll by 1 day (employee relations risk)"
    ],
    "confidence": 0.94
  },
  "reasoning_trace": [
    { "step": 1, "agent": "daily_cash", "status": "complete", "duration_ms": 220, "output": {} },
    { "step": 2, "agent": "liquidity_risk", "status": "complete", "duration_ms": 180, "output": {} },
    { "step": 3, "agent": "forecast", "status": "complete", "duration_ms": 2100, "output": {} },
    { "step": 4, "agent": "policy_check", "status": "complete", "duration_ms": 95, "output": {} },
    { "step": 5, "agent": "recommendation", "status": "complete", "duration_ms": 9200, "output": {} }
  ],
  "created_at": "2026-08-22T09:30:00Z",
  "completed_at": "2026-08-22T09:31:05Z",
  "approved_by": null,
  "approved_at": null
}

// cfo_summaries collection
{
  "job_id": "cfo_20260822_001",
  "client_id": "uuid-client",
  "date": "2026-08-22",
  "narrative": "Cash position is $5.25M across 4 entities...",
  "sections": {
    "cash_position": "...",
    "key_risks": "...",
    "pending_decisions": "...",
    "outlook": "..."
  },
  "created_at": "2026-08-22T07:00:00Z"
}

// pattern_signals collection — NEVER merged with forecast outputs
{
  "client_id": "uuid-client",
  "signal_date": "2026-08-22",
  "signals": [
    {
      "type": "collection_slowdown",
      "description": "AR collections 8% slower vs same quarter last year",
      "confidence": 0.87,
      "supporting_data": { "avg_days_30": 47.2, "avg_days_30_prior_year": 43.7 }
    }
  ],
  "created_at": "2026-08-22T06:00:00Z"
}
```

---

## Integration Patterns

### Frontend ↔ App Backend (REST + SSE)

```
REST (all standard endpoints):
  Frontend → POST /api/recommendations/request   → { request_id, status }
  Frontend → GET  /api/recommendations/{id}      → polls every 5s
  Frontend → POST /api/recommendations/{id}/approve
  Frontend → POST /api/files/upload
  Frontend → GET  /api/cash-position/current
  Frontend → GET  /api/liquidity-risk/current

SSE (chat only):
  Frontend → GET  /ai/chat/stream?session_id=xxx
  AI Backend → streams tokens via SSE
  Frontend renders tokens as they arrive
```

### App Backend → SQS → AI Backend

```
Publish (App Backend):
  job = SQSJobMessage(job_id, job_type, client_id, payload)
  sqs.send_message(QueueUrl=..., MessageBody=job.model_dump_json())

Consume (AI Backend, background task):
  while True:
    msgs = sqs.receive_message(WaitTimeSeconds=20)
    for msg in msgs:
      job = SQSJobMessage.parse(msg.body)
      await orchestrator.run(job)
      sqs.delete_message(ReceiptHandle=msg.receipt_handle)

DLQ handling:
  After 3 failed attempts → message moves to DLQ
  AI Backend monitors DLQ (CloudWatch alarm if DLQ depth > 0)
  Alert to on-call → manual inspection of failed job payload
```

### AI Backend ↔ PostgreSQL (Read-Only)

```python
# ai-backend/app/postgres_readonly.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Separate read-only credentials (IAM user with SELECT only)
readonly_engine = create_async_engine(
    settings.POSTGRES_READONLY_URL,
    pool_size=5,
    max_overflow=10,
    echo=False
)

ReadOnlySession = sessionmaker(readonly_engine, class_=AsyncSession)
```

```python
# ai-backend/app/services/cash_data_service.py
from app.postgres_readonly import ReadOnlySession
from sqlalchemy import select, text

class CashDataService:
    """Read-only access to PostgreSQL for AI agents"""

    async def get_current_position(self, client_id: str) -> dict:
        async with ReadOnlySession() as session:
            result = await session.execute(
                text("""
                    SELECT
                        a.id,
                        a.account_number,
                        a.currency,
                        a.min_threshold,
                        a.is_restricted,
                        a.od_limit,
                        a.od_utilised_amount,
                        CASE
                            WHEN a.od_limit IS NOT NULL
                            THEN a.od_limit - COALESCE(a.od_utilised_amount, 0)
                            ELSE NULL
                        END AS od_headroom,
                        a.refresh_frequency,
                        a.include_in_cash_position,
                        s.closing_balance,
                        s.available_balance,
                        s.statement_date,
                        le.name AS entity_name,
                        b.name AS bank_name
                    FROM accounts a
                    JOIN statements s ON s.account_id = a.id
                    JOIN legal_entities le ON le.id = a.entity_id
                    JOIN banks b ON b.id = a.bank_id
                    WHERE a.client_id = :client_id
                      AND a.include_in_cash_position = TRUE
                      AND s.statement_date = (
                          SELECT MAX(s2.statement_date)
                          FROM statements s2
                          WHERE s2.account_id = a.id
                      )
                """),
                {"client_id": client_id}
            )
            rows = result.mappings().all()
            return [dict(r) for r in rows]
```

---

## Security Architecture

### Authentication Flow

```
Frontend → Cognito (user/password)
Cognito → JWT token (RS256, 1 hour expiry)
Frontend → App Backend: Authorization: Bearer <JWT>
App Backend: Validate JWT signature (Cognito public key, cached)
             Extract claims: sub, email, cognito:groups (roles), client_id
App Backend → SSE/AI endpoints: Forward JWT or service-to-service token
AI Backend: Validate JWT same way (shared Cognito public key)
```

### Role-Based Access Control

```python
# core_cash_shared/types/enums.py
from enum import Enum

class Role(str, Enum):
    VIEWER = "Viewer"
    ANALYST = "Analyst"
    TREASURY_MANAGER = "TreasuryManager"
    CFO = "CFO"

# app-backend/app/dependencies.py
from fastapi import Depends, HTTPException, status
from core_cash_shared.types.enums import Role

def require_role(*roles: Role):
    def dependency(current_user = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {[r.value for r in roles]}"
            )
        return current_user
    return dependency

# Usage in route
@router.post("/{job_id}/approve")
async def approve(
    job_id: str,
    user = Depends(require_role(Role.TREASURY_MANAGER, Role.CFO)),
    service: RecommendationService = Depends(get_recommendation_service)
):
    ...
```

### Data Encryption

```
At Rest:
  PostgreSQL (RDS): AWS KMS (AES-256)
  MongoDB (Atlas): AES-256 at rest
  S3: SSE-S3 (AES-256) or SSE-KMS

In Transit:
  Frontend → ALB: HTTPS TLS 1.2+
  App Backend → PostgreSQL: SSL required
  App Backend → MongoDB: TLS 1.2+
  App Backend → SQS: HTTPS (AWS SDK handles)
  AI Backend → PostgreSQL: SSL required (read-only user)
  AI Backend → MongoDB: TLS 1.2+
  AI Backend → Anthropic API: HTTPS
  App ↔ AI inter-service: Never direct; always via SQS or MongoDB
```

---

## Monitoring & Observability

### Structured Logging (Both Services)

```python
import structlog

logger = structlog.get_logger()

# Every log entry includes context
logger.info("recommendation.queued",
    job_id=job_id,
    client_id=client_id,
    service="app-backend",
    environment="production"
)

logger.error("agent.failed",
    job_id=job_id,
    agent="recommendation_agent",
    error=str(e),
    duration_ms=duration,
    service="ai-backend"
)
```

### CloudWatch Alarms

```hcl
# SQS queue depth alarm (jobs backing up)
resource "aws_cloudwatch_metric_alarm" "sqs_depth_high" {
  alarm_name          = "core-cash-sqs-depth-high"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  evaluation_periods  = 2
  statistic           = "Average"
  threshold           = 50
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  dimensions          = { QueueName = aws_sqs_queue.agent_jobs.name }
}

# DLQ depth alarm (failed jobs)
resource "aws_cloudwatch_metric_alarm" "sqs_dlq_depth" {
  alarm_name          = "core-cash-dlq-not-empty"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  dimensions          = { QueueName = aws_sqs_queue.agent_jobs_dlq.name }
}
```

### Custom Metrics

```
App Backend publishes:
  - recommendation_request_count (per client)
  - file_upload_count (per file_type)
  - approval_rate (approved/total)
  - api_latency_ms (per endpoint)
  - auth_failure_count

AI Backend publishes:
  - job_processing_duration_ms (per job_type)
  - agent_run_duration_ms (per agent_name)
  - llm_call_duration_ms
  - llm_token_usage (input + output tokens per call)
  - sqs_queue_depth (polled)
  - dlq_depth (polled)
```

---

## Disaster Recovery & High Availability

### RDS PostgreSQL

```
Multi-AZ: Yes (automatic failover, < 1 min)
Backup: 35-day point-in-time restore
Read Replica: 1 (AI backend read-only traffic)
```

### MongoDB (Atlas)

```
3-node replica set (automatic failover)
Continuous backup (point-in-time, 35 days)
```

### AWS SQS

```
Durability: 99.999999999% (AWS guarantee)
Message retention: 4 days (jobs safe even if AI backend down)
Dead-letter queue: catches failed jobs after 3 retries
No data loss even during ECS restart
```

### ECS Fargate

```
App Backend: 2 tasks minimum (1 per AZ), auto-scale 2–6
AI Backend: 2 tasks minimum (1 per AZ), auto-scale 2–4
Health checks: /health every 30s, replace failed tasks in < 2 min
```

---

## Deployment & CI/CD

### Monorepo CI/CD (GitHub Actions)

```yaml
name: Deploy Core Cash Backend

on:
  push:
    branches: [main]

jobs:
  build-shared:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Test shared library
        run: |
          cd shared
          pip install -e ".[test]"
          pytest

  build-app-backend:
    needs: build-shared
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Test app backend
        run: |
          cd app-backend
          pip install poetry
          poetry install
          pytest
      - name: Build & push Docker image
        run: |
          docker build \
            --build-arg SERVICE=app-backend \
            -t $ECR_REGISTRY/core-cash-app:$GITHUB_SHA .
          docker push $ECR_REGISTRY/core-cash-app:$GITHUB_SHA
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster core-cash-cluster \
            --service core-cash-app-service \
            --force-new-deployment

  build-ai-backend:
    needs: build-shared
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Test AI backend
        run: |
          cd ai-backend
          pip install poetry
          poetry install
          pytest
      - name: Build & push Docker image
        run: |
          docker build \
            --build-arg SERVICE=ai-backend \
            -t $ECR_REGISTRY/core-cash-ai:$GITHUB_SHA .
          docker push $ECR_REGISTRY/core-cash-ai:$GITHUB_SHA
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster core-cash-cluster \
            --service core-cash-ai-service \
            --force-new-deployment
```

---

## Cost Optimization

### Monthly Cost Per Customer (v2.0)

| Component | v1.0 (.NET + Python) | v2.0 (Python + Python) | Delta |
|---|---|---|---|
| ECS App Backend | $80–100 (.NET) | $70–90 (Python) | -$10 |
| ECS AI Backend | $100–120 | $100–120 | No change |
| RDS PostgreSQL | $150–200 | $150–200 | No change |
| MongoDB (Atlas M10) | — | $57 | +$57 |
| ElastiCache Redis | $30–40 | $0 (removed) | -$35 |
| AWS SQS | — | $1–5 | +$3 |
| S3 / ALB / NAT / Other | $100–120 | $100–120 | No change |
| **TOTAL** | **$460–580** | **$478–592** | **~+$18** |

**Net infrastructure impact: negligible** (~$18/month increase per customer — MongoDB replaces Redis; SQS replaces Redis queue; Python slightly cheaper than .NET on Fargate). Gross margin remains 75–85%.

---

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1–3)
- [ ] AWS infrastructure (VPC, RDS, MongoDB Atlas, SQS, ECS, ALB, ECR)
- [ ] Shared Python library scaffold (schemas, types, utils) — **built first, both services depend on it**
- [ ] App backend: FastAPI skeleton, auth, health check
- [ ] AI backend: FastAPI skeleton, SQS consumer, health check
- [ ] CI/CD pipeline (monorepo GitHub Actions)

### Phase 2: App Backend Core (Weeks 4–6)
- [ ] File upload + S3 integration
- [ ] BAI2, camt.053, CSV parsers (Excel excluded from MVP)
- [ ] PostgreSQL schema + Alembic migrations
- [ ] Cash position service + endpoint
- [ ] Account master CRUD
- [ ] Recommendation request → SQS publish
- [ ] Recommendation poll endpoint (reads MongoDB)

### Phase 3: AI Backend Core (Weeks 5–7, parallel)
- [ ] SQS consumer (background task)
- [ ] PostgreSQL read-only connection
- [ ] LangGraph agent graph setup
- [ ] Daily Cash Position Agent (Agent 1) — deterministic, no LLM
- [ ] Liquidity Risk Agent (Agent 3) — deterministic, no LLM
- [ ] MongoDB result writer
- [ ] End-to-end test: SQS → Agents → MongoDB → Poll

### Phase 4: Remaining Agents (Weeks 7–9)
- [ ] Forecast Intelligence Agent (Agent 2) — **BLOCKED**: opening balance anchor unresolved (pending decision with amit j)
- [ ] Action Recommendation Agent (Agent 4) — Claude Sonnet (mocked in build sessions)
- [ ] Variance Explanation Agent (Agent 5) — Claude Sonnet (mocked; blocked by Agent 2)
- [ ] CFO Summary Agent (Agent 6) — Claude Sonnet (mocked in build sessions)
- [ ] Treasury Continuity Agent (Agent 7) — deterministic retrieval from MongoDB recommendations
- [ ] Policy-aware Control Agent (Agent 8) — deterministic middleware
- [ ] SSE chat endpoint (AI Backend)

### Phase 5: Production Hardening (Weeks 10–13)
- [ ] DLQ monitoring + alerting
- [ ] Structured logging (CloudWatch)
- [ ] Custom metrics (CloudWatch)
- [ ] Security review (encryption, RBAC, audit trail)
- [ ] Load testing (k6)
- [ ] UAT with pilot customer
- [ ] Real LLM wiring for Agents 4, 5, 6 (post-Step-8 sign-off, dedicated session)

---

## Conclusion

The v2.1 architecture adopts a **unified Python dual-service model** that eliminates the .NET boundary, introduces a shared Pydantic schema library as the single source of truth, replaces Redis with AWS SQS for job queuing, and adds MongoDB as the document store for agent outputs.

**Key design decisions:**
1. **Shared lib** eliminates schema drift — the #1 integration risk in a dual-service model
2. **SQS over Redis** — durable, managed, DLQ native, cheaper for this workload
3. **MongoDB for agent outputs** — document shape fits; no FK constraints needed; fast polling
4. **PostgreSQL read-only access in AI Backend** — validated data only; AI never corrupts core tables
5. **SSE for chat** — streaming response appropriate for chat; REST for everything else
6. **Both services deploy independently** — one service's deployment doesn't block the other
7. **od_headroom is computed, never stored** — calculated as `od_limit - od_utilised_amount` in the service layer
8. **decision_log deferred** — MongoDB recommendations collection serves Agent 7 in MVP

---

**Document Version:** 2.1
**Supersedes:** v2.0 (August 22, 2026)
**Last Updated:** August 22, 2026
**Changes in v2.1:** Added `od_limit`, `od_utilised_amount`, `refresh_frequency`, `include_in_cash_position` to `accounts` DDL; `od_headroom` documented as computed field; `decision_log` explicitly deferred to Phase 2; `cash_data_service.py` updated to compute `od_headroom` and filter by `include_in_cash_position`.
**Ready for:** Architecture Review, Development Team Handoff