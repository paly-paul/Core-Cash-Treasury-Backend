# Configuration and Environment Variables

All configuration is read from environment variables at startup. **No secrets stored in code.**

---

## Environment Variables — By Service

### Shared Variables (Both App Backend & AI Backend)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string. Format: `postgresql://user:pass@host:5432/dbname`. App Backend: R/W access. AI Backend: read-only. |
| `MONGODB_URI` | ✅ | — | MongoDB connection string. Format: `mongodb://host:27017` or `mongodb+srv://...` (Atlas). |
| `MONGODB_DB_NAME` | ✅ | — | MongoDB database name (e.g., `core_cash_test`, `core_cash_prod`). |
| `AWS_REGION` | ✅ | `us-east-1` | AWS region for Cognito and SQS. |
| `COGNITO_REGION` | ✅ | `us-east-1` | Cognito region (usually same as AWS_REGION). |
| `COGNITO_USER_POOL_ID` | ✅ | — | Cognito User Pool ID (e.g., `us-east-1_test12345`). |
| `COGNITO_APP_CLIENT_ID` | ✅ | — | Cognito App Client ID for JWT validation. |
| `ANTHROPIC_API_KEY` | ✅ | `placeholder-test-key` | Anthropic API key for Claude LLM. Development: use placeholder; production: real API key. |
| `AI_BACKEND_URL` | ✅ | `http://localhost:8001` | URL of AI Backend service (used by app-backend chat proxy). |
| `TEST_JWT_SECRET` | ❌ | — | JWT signing key for test environment only (dev only; not used in production). |

---

### App Backend Only

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SQS_QUEUE_URL` | ✅ | — | SQS queue URL for job publishing (development: use local ElasticMQ; production: AWS SQS). Format: `http://localhost:9324/000000000000/core-cash-jobs` (local) or `https://sqs.region.amazonaws.com/account/queue-name` (AWS). |
| `DB_POOL_SIZE` | ❌ | `10` | SQLAlchemy connection pool size (max concurrent connections). |
| `DB_POOL_RECYCLE` | ❌ | `3600` | Connection recycle timeout in seconds (PostgreSQL idle timeout). |
| `LOG_LEVEL` | ❌ | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). |

---

### AI Backend Only

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CONSUMER_TYPE` | ❌ | `in_process` | Job consumer type: `in_process` (in-memory queue) or `sqs` (AWS SQS). Development: use `in_process`; production: use `sqs`. |
| `LOG_LEVEL` | ❌ | `INFO` | Logging level. |

---

## Database Connection Strings

### PostgreSQL (App Backend: R/W, AI Backend: R/O)

```bash
# Local development (Docker)
DATABASE_URL=postgresql://postgres:postgres@db:5432/core_cash_test

# Local development (host)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/core_cash_test

# Production (managed RDS)
DATABASE_URL=postgresql://app_user:strong_password@db.example.com:5432/core_cash_prod

# With SSL
DATABASE_URL=postgresql://user:pass@host:5432/db?sslmode=require
```

**Important**: 
- App Backend: Needs INSERT, UPDATE, DELETE on all tables
- AI Backend: Needs SELECT only (verified on startup via `verify_read_only()`)

### MongoDB

```bash
# Local development (Docker)
MONGODB_URI=mongodb://mongo:27017
MONGODB_DB_NAME=core_cash_test

# Local development (host)
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=core_cash_test

# Atlas (managed MongoDB)
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB_NAME=core_cash_prod
```

---

## Cognito Configuration

### How to Get Credentials

1. **User Pool ID**: AWS Cognito → User Pools → Core Cash Pool → Pool ID
   - Format: `us-east-1_abc12345`
   - Matches `COGNITO_REGION` prefix

2. **App Client ID**: AWS Cognito → User Pools → Core Cash Pool → App Integration → App Client Settings
   - Format: UUID or alphanumeric string

3. **JWKS Public Key**: Cognito automatically serves public keys at:
   ```
   https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json
   ```
   - App Backend fetches this on startup to validate JWT signatures
   - No configuration needed; automatic discovery

---

## LLM Configuration

### ANTHROPIC_API_KEY

**Development** (Placeholder Mode):
```bash
ANTHROPIC_API_KEY=placeholder-test-key
```

When set to placeholder:
- LLM-dependent endpoints (Agent 4, 5, 6) return fixed mock responses
- All numeric data (balances, scores) remains accurate
- Service starts and operates normally
- No API calls made; no charges incurred

**Production** (Real LLM):
```bash
ANTHROPIC_API_KEY=sk-ant-v0-abc123...
```

When set to real key:
- Agent 4 (Action Recommendation): calls Claude API with treasury analysis prompt
- Agent 5 (Variance Explanation): calls Claude API to analyze forecast misses
- Agent 6 (CFO Summary): calls Claude API to generate executive brief
- Session 15 feature (Post-MVP)

---

## System Configuration

### Writable Keys (Only 3)

These values live in PostgreSQL `system_config` table and can be updated via API.

#### 1. `forecast_confidence_threshold`

**Default**: `50`

**Used by**: Agent 2 (Forecast) to filter manual assumptions

**Logic**: Only assumptions with `confidence_pct >= forecast_confidence_threshold` are included in forecast

**Valid Range**: 0–100

**Update Endpoint**: `PUT /api/config/system/forecast_confidence_threshold`

```json
{
  "config_val": "60"  // Changed from 50 to 60
}
```

---

#### 2. `warning_threshold_pct`

**Default**: `70`

**Used by**: Agent 3 (Liquidity Risk) to flag warning status

**Logic**: `is_warning = true` if `cash_balance / cash_required < (warning_threshold_pct / 100)`

**Valid Range**: 0–100

**Important**: This value is **NEVER 80** per business rule. Minimum safe threshold is 70%.

**Update Endpoint**: `PUT /api/config/system/warning_threshold_pct`

---

#### 3. `significant_outflow_pct`

**Default**: `10`

**Used by**: Agent 3 (Liquidity Risk) to score outflow significance

**Logic**: Outflows > (total_balance * significant_outflow_pct / 100) are flagged

**Valid Range**: 0–100

**Update Endpoint**: `PUT /api/config/system/significant_outflow_pct`

---

### Read-Only Values (Post-MVP)

These are concepts for future sessions; currently not wired:

- `forecast_model_type`: "placeholder" or "arima" (Session 14)
- `variance_tolerance_pct`: 5 (never display ±3%; always show ±5%)
- `sqs_max_visibility_timeout`: 300 seconds
- `mongodb_ttl_days`: 90 (for archive collections)

---

## Job Queue Configuration

### Development (InProcess)

```bash
# app-backend/.env
# (No SQS_QUEUE_URL needed; uses InProcessJobPublisher)
```

**How it works**:
- App Backend: Publishes JobEnvelope to in-memory queue
- AI Backend consumer: Pulls from same in-memory queue (shared process)
- No SQS dependency; entire pipeline runs in-process
- Perfect for development and testing

### Production (AWS SQS)

```bash
# app-backend/.env
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789/core-cash-jobs

# ai-backend/.env
CONSUMER_TYPE=sqs
```

**How it works**:
1. App Backend: Publishes JobEnvelope to SQS queue
2. AI Backend consumer: Polls SQS (long-polling, 10–20 second wait)
3. Processes job, updates job_status table (PostgreSQL)
4. Deletes message from SQS queue
5. Repeats

**Parallelism**: Multiple AI Backend instances can consume from same queue (load balanced by SQS)

---

## Startup Behavior When ANTHROPIC_API_KEY Is Placeholder

When `ANTHROPIC_API_KEY=placeholder-test-key`:

1. **Service Starts Normally**: No validation error; service does not halt
2. **Database Connections**: PostgreSQL and MongoDB connections proceed normally
3. **Agent Execution**: All agents run and produce results
4. **Numeric Data**: All balance, score, and forecast data is accurate
5. **LLM Fields**: Mocked
   - Agent 4 recommendations: Return fixed "Invest surplus" recommendations
   - Agent 5 variance: Return template "Forecast missed by [amount]" explanations
   - Agent 6 CFO summary: Return fixed summary structure
6. **No API Calls**: LangGraph integrations skip; no Anthropic API requests made
7. **No Charges**: Zero API costs in development

**Example Response** (Agent 4 with placeholder key):

```json
{
  "recommendations": [
    {
      "id": "rec_mock_001",
      "what": "Invest USD 500k surplus in money market fund",
      "why": "[MOCK] Excess liquidity detected; 30-day forecast shows positive trajectory",
      "priority": 1,
      "approval_status": "Pending"
    }
  ]
}
```

---

## Environment File Examples

### .env.example (App Backend)

```bash
# PostgreSQL
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/core_cash_test
DB_POOL_SIZE=10
DB_POOL_RECYCLE=3600

# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=core_cash_test

# Job Queue (development)
SQS_QUEUE_URL=http://localhost:9324/000000000000/core-cash-jobs

# AWS
AWS_REGION=us-east-1

# Cognito
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_test12345
COGNITO_APP_CLIENT_ID=test_client_id_123

# LLM
ANTHROPIC_API_KEY=placeholder-test-key

# Services
AI_BACKEND_URL=http://localhost:8001

# Testing
TEST_JWT_SECRET=test-secret-key-for-signing-jwts-in-tests

# Logging
LOG_LEVEL=INFO
```

### .env.example (AI Backend)

```bash
# PostgreSQL (read-only)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/core_cash_test

# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=core_cash_test

# AWS
AWS_REGION=us-east-1

# Cognito (for reading JWT claims if needed)
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_test12345
COGNITO_APP_CLIENT_ID=test_client_id_123

# LLM
ANTHROPIC_API_KEY=placeholder-test-key

# Job Consumer
CONSUMER_TYPE=in_process

# Services
AI_BACKEND_URL=http://localhost:8001

# Testing
TEST_JWT_SECRET=test-secret-key-for-signing-jwts-in-tests

# Logging
LOG_LEVEL=INFO
```

---

## Docker Compose Example

```yaml
version: "3.9"
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: core_cash_test
    ports:
      - "5432:5432"

  mongo:
    image: mongo:6
    ports:
      - "27017:27017"

  app-backend:
    build: ./app-backend
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/core_cash_test
      MONGODB_URI: mongodb://mongo:27017
      MONGODB_DB_NAME: core_cash_test
      COGNITO_REGION: us-east-1
      COGNITO_USER_POOL_ID: us-east-1_test12345
      COGNITO_APP_CLIENT_ID: test_client_id_123
      ANTHROPIC_API_KEY: placeholder-test-key
      AI_BACKEND_URL: http://ai-backend:8001
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - mongo

  ai-backend:
    build: ./ai-backend
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/core_cash_test
      MONGODB_URI: mongodb://mongo:27017
      MONGODB_DB_NAME: core_cash_test
      COGNITO_REGION: us-east-1
      COGNITO_USER_POOL_ID: us-east-1_test12345
      COGNITO_APP_CLIENT_ID: test_client_id_123
      ANTHROPIC_API_KEY: placeholder-test-key
      CONSUMER_TYPE: in_process
      AI_BACKEND_URL: http://ai-backend:8001
    ports:
      - "8001:8001"
    depends_on:
      - postgres
      - mongo
```

---

## Troubleshooting

### "Failed to verify read-only database"
- **Cause**: AI Backend detected write permission on PostgreSQL
- **Fix**: AI Backend should use read-only connection string (check database user permissions)

### "Failed to connect to MongoDB"
- **Cause**: MONGODB_URI unreachable or wrong database name
- **Fix**: Verify MONGODB_URI and MONGODB_DB_NAME; check MongoDB is running

### "Auth token invalid"
- **Cause**: JWT signature invalid (Cognito public key mismatch)
- **Fix**: Verify COGNITO_USER_POOL_ID and COGNITO_REGION match your Cognito setup

### "Forecast confidence threshold not found"
- **Cause**: system_config table missing entry
- **Fix**: Defaults to 50; if needed, insert: `INSERT INTO system_config (client_id, config_key, config_val) VALUES ('...', 'forecast_confidence_threshold', '50')`

### "ANTHROPIC_API_KEY not set; using placeholder"
- **Behavior**: Normal; all agents produce mock responses
- **Fix**: Set real API key in production; leave placeholder for development

---

## Configuration Checklist

### Startup Validation

Core Cash validates the following on startup:

- ✅ PostgreSQL connection (app-backend: R/W, ai-backend: R/O)
- ✅ MongoDB connection
- ✅ Cognito user pool reachable
- ✅ AI Backend URL reachable (app-backend only)
- ✅ Migrations applied (alembic upgrade head)
- ✅ Fixtures loaded (app-backend only)

If any check fails, service exits with error message.

---

## Performance Tuning

### Database Connection Pool

```bash
# For high concurrency (production)
DB_POOL_SIZE=20
DB_POOL_RECYCLE=1800
```

### MongoDB Connection

MongoDB driver auto-scales connection pool; no config needed.

### Logging Level

```bash
# Development
LOG_LEVEL=DEBUG

# Production
LOG_LEVEL=WARNING
```

Next: [Frontend Integration Guide →](06-frontend-integration-guide.md)
