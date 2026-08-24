# Session 11 Complete — Chat SSE Endpoint (Mocked)

**Status:** Complete  
**Date:** 2026-08-24  
**Branch:** `claude/chat-sse-endpoint-a8krkq`

---

## Summary

Session 11 implements the Chat SSE (Server-Sent Events) endpoint in the AI Backend. This endpoint allows treasury users to ask natural-language questions about their cash position, recommendations, and risk alerts. The AI Backend streams a response token-by-token over SSE. The App Backend proxies this stream directly to the browser.

LLM responses are mocked in this session using contextual template strings. Real Anthropic API wiring happens in Session 12.

---

## What Was Built

### Files Created

**Shared Schemas:**
```
shared/core_cash_shared/schemas/chat.py                    (20 lines)
  - ChatMessage: role (user|assistant) + content
  - ChatRequest: messages list, entity_id, session_id
  - ChatSSEEvent: event type + data (token|done|error|context)
```

**AI Backend Services:**
```
ai-backend/app/services/chat_context.py                    (60 lines)
  - load_chat_context(): MongoDB + PostgreSQL SELECT-only reads
  - Loads: cash_position, risk_level, risk_score, active_breaches, pending_recs
  - Never returns None — returns empty defaults on error

ai-backend/app/services/chat_prompt.py                     (35 lines)
  - build_system_prompt(): Formats template with context data
  - System prompt tailored to treasury domain
  - Includes entity name, cash position, risk level, breach count, pending count

ai-backend/app/services/mock_llm.py                        (45 lines)
  - mock_stream_response(): AsyncGenerator yielding tokens
  - Routes on keyword match (cash, risk, recommend, forecast, generic)
  - 50ms/token delay to simulate streaming
  - Ready for real Anthropic client swap in Session 12

ai-backend/app/auth/jwt.py                                 (50 lines)
  - JWTValidator: Cognito RS256 token validation
  - Checks expiration, issuer, signature
  - Extracted client_id from token.sub for context scoping

ai-backend/app/auth/dependencies.py                        (30 lines)
  - get_current_user(): Dependency for role extraction
  - Returns {user_id, email, role}

ai-backend/app/routes/chat.py                              (65 lines)
  - POST /chat/stream (SSE endpoint)
  - Validates: JWT, messages non-empty, last message is user role
  - Returns 422 before stream opens on validation failure
  - Event sequence: context → tokens → done
  - Uses EventSourceResponse from sse-starlette
```

**AI Backend Config Update:**
```
ai-backend/app/config.py
  - Added: cognito_region, cognito_user_pool_id, cognito_app_client_id
  - Added: ai_backend_url (default: http://localhost:8001)
```

**App Backend Proxy:**
```
app-backend/app/routers/chat_proxy.py                      (75 lines)
  - POST /api/chat/stream (proxy endpoint)
  - Forwards ChatRequest to AI Backend with Authorization header
  - Streams response bytes directly (no buffering)
  - Error handling: 503 on connect error, JSON error response

app-backend/app/config.py
  - Added: ai_backend_url (default: http://localhost:8001)
```

**Tests:**
```
ai-backend/tests/test_chat_stream.py                       (100+ lines)
  - test_mock_streamer_produces_tokens: Verify tokens are yielded
  - test_system_prompt_builder: Verify context injection
  - test_system_prompt_builder_empty_context: Verify defaults
  - test_mock_streamer_cash_question: Keyword routing
  - test_mock_streamer_risk_question: Keyword routing
  - test_mock_streamer_recommendation_question: Keyword routing
  - test_mock_streamer_generic_question: Fallback response

app-backend/tests/test_chat_proxy.py                       (150+ lines)
  - test_chat_proxy_requires_auth: JWT validation enforced
  - test_chat_proxy_forwards_auth_header: Authorization header forwarded
  - test_chat_proxy_ai_backend_unavailable: Connection error handling
  - test_chat_proxy_handles_non_200_response: Non-2xx status handling
```

### Files Modified

```
shared/core_cash_shared/schemas/__init__.py
  - Exported: ChatMessage, ChatRequest, ChatSSEEvent

ai-backend/pyproject.toml
  - Added: sse-starlette>=1.6

ai-backend/app/main.py
  - Imported: chat router
  - Registered: app.include_router(chat.router, prefix="/chat", tags=["Chat"])

app-backend/pyproject.toml
  - Moved httpx from dev to main dependencies

app-backend/app/main.py
  - Imported: chat_proxy router
  - Registered: app.include_router(chat_proxy.router, prefix="/api/chat", tags=["Chat"])
```

---

## Architecture

### Chat is Unique

Chat is the **ONLY feature** that:
- Uses SSE (not the async job pattern)
- Lives entirely in the AI Backend (no App Backend job_requests row)
- Calls the LLM directly (mocked here; real in Session 12)
- Streams token-by-token in real time

### Request Flow

```
Browser
  ↓ POST /api/chat/stream (with JWT)
App Backend
  ↓ Validate JWT, forward ChatRequest
AI Backend
  ↓ Validate JWT independently
  ↓ Load context (MongoDB + PostgreSQL)
  ↓ Build system prompt
  ↓ Stream tokens from mock_stream_response()
  ↓ SSE events: context → token+ → done
App Backend
  ↓ Stream SSE events directly to browser
Browser
```

### JWT Validation

Both services validate the JWT independently using the same Cognito keys:
- `cognito_region`, `cognito_user_pool_id`, `cognito_app_client_id` from `.env`
- Checks expiration, issuer, signature
- Extracts `client_id` from token.sub

### SSE Event Format

```
event: context
data: {"cash_position": ..., "risk_level": ..., ...}

event: token
data: Based

event: token
data:  on the

event: token
data:  latest

event: done
data: done
```

---

## MongoDB Collections Read (Never Written by Chat)

- `cash_positions` — Agent 1 output (latest by computed_at)
- `liquidity_risk` — Agent 3 output (latest by computed_at)
- `recommendations` — Agent 4 output, filtered by approval_status=Pending

---

## PostgreSQL Reads (SELECT-only)

- `entities` — entity metadata (for entity_id → client_id validation in future sessions)

---

## Key Rules Implemented

✅ Chat never writes to any database  
✅ Chat never executes or approves recommendations  
✅ JWT validated independently in both services  
✅ No timeout on SSE streaming (httpx timeout=None)  
✅ Mock streamer: 50ms/token delay, routes on keyword match  
✅ X-Accel-Buffering: no header (nginx proxy compatibility)  
✅ EventSourceResponse from sse-starlette (correct SSE format)  
✅ Context emitted first (UI can display data immediately)  
✅ No buffering — tokens yielded immediately  
✅ Error events close stream gracefully  

---

## Testing

### AI Backend Tests (7 tests)
- Mock streamer produces non-empty tokens
- System prompt builder injects context correctly
- System prompt builder handles empty context (defaults)
- Keyword routing: cash, risk, recommend, forecast, generic
- All assertions verify token generation and content

### App Backend Tests (4 tests)
- JWT required (403 without)
- Authorization header forwarded verbatim
- Connection errors handled (500)
- Non-2xx AI Backend responses handled (503)

---

## Dependencies Added

```
ai-backend/pyproject.toml
  + sse-starlette>=1.6

app-backend/pyproject.toml
  + httpx>=0.24 (moved from dev to main)
```

---

## Deployment Notes

### Environment Variables Required

Both services require:
```
COGNITO_REGION=...              # e.g., us-east-1
COGNITO_USER_POOL_ID=...        # e.g., us-east-1_xxxxx
COGNITO_APP_CLIENT_ID=...       # Cognito app client ID
```

AI Backend only:
```
AI_BACKEND_URL=http://localhost:8001  # Default; override for prod
```

App Backend only:
```
AI_BACKEND_URL=http://localhost:8001  # Default; override for prod
```

---

## Known Limitations

### Until Session 12 (Real LLM Wiring)

- Mock responses route on simple keyword matching
- No actual LLM inference
- No conversation history (stateless per request)
- ANTHROPIC_API_KEY placeholder (not used yet)

### Out of Scope (MVP)

- Ad-hoc analysis beyond agent outputs
- Raw transaction queries
- Writing assumptions via chat
- Approving recommendations via chat
- Conversation history storage
- Session persistence

---

## TODO — Session 12

- Replace mock_llm.py streamer with real Anthropic streaming client
- Wire ANTHROPIC_API_KEY from .env
- Implement real message → token streaming
- Test with actual Anthropic API (mocked in integration tests first)
- Add conversation context (if required by product)

---

## TODO — Session 12+ (Agents 4, 5, 6)

- Replace mock responses in Agents 4, 5, 6 with real LLM calls
- Integrate Agent outputs into system prompt (not just context snapshot)

---

## Verification Checklist

✅ Shared chat schemas created (ChatMessage, ChatRequest, ChatSSEEvent)  
✅ Chat context loader reads MongoDB + PostgreSQL (SELECT-only)  
✅ System prompt builder injects context into template  
✅ Mock LLM streamer yields tokens with 50ms delay  
✅ AI Backend chat router validates JWT independently  
✅ AI Backend chat router validates ChatRequest (non-empty, last=user)  
✅ AI Backend returns 422 before stream opens on invalid input  
✅ SSE event sequence: context → tokens → done  
✅ App Backend proxy forwards ChatRequest to AI Backend  
✅ App Backend proxy forwards Authorization header verbatim  
✅ App Backend proxy streams response bytes directly (no buffering)  
✅ App Backend proxy handles connect errors (503)  
✅ App Backend proxy handles non-2xx responses (503)  
✅ Both services independently validate JWT  
✅ No timeout on SSE httpx client  
✅ Tests cover mock streamer, system prompt, proxy forwarding  
✅ Dependencies added (sse-starlette, httpx)  

---

## Sessions Remaining

- **Session 12:** Real LLM wiring (Anthropic API + Agents 4, 5, 6)
- **Session 13:** Agent 2 Forecast Full (blocked placeholder)
- **Session 14:** Forecast unblock + Agent 2 live

---

**End of Session 11. Chat SSE endpoint complete with mocked responses. Ready for Session 12 (Real LLM wiring).**
