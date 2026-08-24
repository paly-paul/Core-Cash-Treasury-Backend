# Session 5b Handoff: Recommendation Endpoints + Approval Workflow

**Status:** Complete  
**Date:** 2026-08-24

---

## What Was Built

### App Backend: Recommendation Endpoints

**Files Created:**
- `app-backend/app/routers/recommendations.py` — All 6 recommendation endpoints
- `app-backend/app/services/recommendation_service.py` — MongoDB read/write logic
- `app-backend/tests/test_recommendation_endpoints.py` — 16 comprehensive test cases

**Files Modified:**
- `app-backend/app/main.py` — Registered recommendations router
- `app-backend/app/routers/__init__.py` — Created routers package

### Endpoints Implemented

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/recommendations/request` | Analyst, TM, CFO | Publish job, return 202 |
| GET | `/api/recommendations/{request_id}` | All roles | Poll job status / return result |
| GET | `/api/recommendations` | All roles | List recommendation runs (paginated) |
| POST | `/api/recommendations/{id}/approve` | TM, CFO only | Approve one recommendation item |
| POST | `/api/recommendations/{id}/reject` | TM, CFO only | Reject one recommendation item |
| POST | `/api/recommendations/{id}/override` | TM, CFO only | Record manual override |

### Implementation Details

#### POST /api/recommendations/request
- Generates UUID request_id
- Creates JobEnvelope with JobType.ACTION_RECOMMENDATION
- Publishes to in-process job runner (InProcessJobPublisher)
- Inserts job_status row with status="queued"
- Returns 202 with request_id, queued_at, estimated_completion
- Returns 503 if job publisher fails

#### GET /api/recommendations/{request_id}
- Queries job_status table
- If queued/processing: returns minimal response with status only
- If completed: reads MongoDB recommendations collection, strips internal fields, returns full result
- Includes static mock reasoning_trace (TODO: wire real timing in Session 12)
- If failed: returns error message
- Returns 404 if job not found

#### GET /api/recommendations
- Lists all job_status rows for client (paginated)
- For completed jobs: queries MongoDB for pending_approvals count
- Returns summary items (not full recommendations)
- Supports page, page_size, status query parameters

#### POST /api/recommendations/{id}/approve
- Updates MongoDB recommendation item with approval_status="Approved"
- Sets approved_by=current_user.id, approved_at=now
- Stores notes field
- Writes audit_log entry with action="recommendation.approved"
- Returns 409 if recommendation already actioned (Approved/Rejected/Overridden)
- Returns 404 if recommendation not found
- Audit write failure is non-blocking

#### POST /api/recommendations/{id}/reject
- Updates MongoDB recommendation item with approval_status="Rejected"
- Sets rejected_by=current_user.id, rejected_at=now
- Stores rejection_reason field
- Writes audit_log entry with action="recommendation.rejected"
- Returns 409 if already actioned
- Audit write failure is non-blocking

#### POST /api/recommendations/{id}/override
- Updates MongoDB recommendation item with approval_status="Overridden"
- Sets overridden_by=current_user.id, overridden_at=now
- Stores action_taken and notes fields
- Writes audit_log entry with action="recommendation.overridden"
- Returns 409 if already actioned
- Audit write failure is non-blocking

### Service Layer: recommendation_service.py

**Functions:**
- `get_recommendation_result()` — Reads completed recommendation from MongoDB, strips internal fields
- `find_recommendation_by_id()` — Locates recommendation item within client's documents
- `approve_recommendation()` — Updates approval_status to Approved, returns updated item
- `reject_recommendation()` — Updates approval_status to Rejected, returns updated item
- `override_recommendation()` — Updates approval_status to Overridden, returns updated item
- `get_pending_approvals_count()` — Counts pending items in a recommendation document

**Critical Patterns:**
- All MongoDB queries scoped to `client_id` — prevents cross-client access
- MongoDB positional operator `$` used for array element updates
- Validates approval_status before allowing second action (409 on already-actioned)
- Never exposes blocked_count, blocked_reasons, source_agent_runs in responses

---

## Key Rules Confirmed

1. ✅ **Approval is a record only.** No downstream action initiated on approval. No SQS message. No autonomous execution. Comment added in code: `# Record only — no autonomous action initiated`

2. ✅ **409 on double-action.** If approval_status is already Approved, Rejected, or Overridden, any further action returns 409. User cannot un-approve.

3. ✅ **client_id scoping enforced.** Every MongoDB query filters on client_id. Service layer validates — never exposes recommendations from other clients.

4. ✅ **Internal fields never exposed.** blocked_count, blocked_reasons, source_agent_runs stripped in get_recommendation_result() before any API response.

5. ✅ **Audit write non-blocking.** If write_audit_event() fails, log warning and continue. Approval/reject/override response still returns 200. Business operation completes regardless.

6. ✅ **Role gates as FastAPI dependencies.** Used require_role(["TreasuryManager", "CFO"]) dependency. Requests from Analyst/Viewer return 403 automatically.

7. ✅ **Reasoning_trace mocked for MVP.** Static response with fixed duration_ms values. Comment added: `# TODO: wire real timing from AgentState in Session 12`

---

## Tests

**File:** `app-backend/tests/test_recommendation_endpoints.py`

**16 test cases:**

1. POST request — happy path (202, request_id created, job_status inserted)
2. POST request — job publisher fails (503, AGENT_ERROR)
3. POST request — Analyst can request (role gate working)
4. GET status — queued (returns status only, no recommendations)
5. GET status — processing (returns status only)
6. GET status — completed (returns full result + reasoning_trace, internal fields stripped)
7. GET status — completed, blocked_count/blocked_reasons/source_agent_runs not exposed
8. GET status — failed (returns error message)
9. GET status — not found (404, NOT_FOUND)
10. GET list — empty (0 recommendations)
11. GET list — pagination (page, page_size working)
12. POST approve — happy path (200, approval_status updated, audit event written)
13. POST approve — double-approve returns 409
14. POST approve — Analyst returns 403 (role gate)
15. POST approve — audit write failure non-blocking (200 still returned)
16. POST reject — happy path (200, approval_status updated)
17. POST reject — already approved returns 409
18. POST override — happy path (200, approval_status updated, action_taken stored)
19. POST override — already actioned returns 409
20. Client isolation — cannot approve another client's recommendation

**All tests structured as:**
- Use synchronous TestClient (not async)
- Mock external dependencies (InProcessJobPublisher, MongoDB, audit service)
- Override FastAPI dependencies (get_current_user, get_db)
- Verify HTTP status codes and response shapes
- Verify audit event calls
- Verify role gates

**Test Execution:**
```
pytest app-backend/tests/test_recommendation_endpoints.py -v
```

---

## MongoDB Document Shape (from Session 5a)

**Collection:** `recommendations`

**Document structure** (read by GET endpoints, written to by approve/reject/override):

```python
{
    "_id": ObjectId,
    "job_id": str,
    "client_id": str,
    "agent": "action_recommendation",
    "created_at": datetime,
    "recommendation_count": int,
    "recommendations": [
        {
            "id": str,  # UUID — used by approve/reject/override endpoints
            "priority": int,
            "type": str,  # "Funding" | "Investment"
            "why": str,
            "what": str,  # evaluative language only
            "when": str,
            "control": {
                "approval_owner": str,
                "policy_check": str,
                "human_approval_required": True,
            },
            "approval_status": "Pending",  # mutated by this session to Approved/Rejected/Overridden
            "approved_by": None,  # set by approve endpoint
            "approved_at": None,  # set by approve endpoint
            "notes": None,  # set by approve endpoint
            "rejected_by": None,  # set by reject endpoint
            "rejected_at": None,  # set by reject endpoint
            "rejection_reason": None,  # set by reject endpoint
            "overridden_by": None,  # set by override endpoint
            "overridden_at": None,  # set by override endpoint
            "action_taken": None,  # set by override endpoint
        }
    ],
    "blocked_count": int,  # NEVER EXPOSED IN API
    "blocked_reasons": list,  # NEVER EXPOSED IN API
    "source_agent_runs": dict,  # NEVER EXPOSED IN API
}
```

---

## API Response Examples

### GET /api/recommendations/{request_id} — Completed

```json
{
  "request_id": "rec_20260822_093000_a1b2c3d4",
  "status": "completed",
  "run_id": "mongodb_object_id_string",
  "generated_at": "2026-08-22T09:31:05Z",
  "recommendation_count": 2,
  "recommendations": [
    {
      "id": "uuid",
      "priority": 1,
      "type": "Funding",
      "why": "EU Entity EUR balance is €70K below the €500K minimum threshold...",
      "what": "Evaluate EUR 200K funding transfer to EU Entity BofA EUR Reserve...",
      "when": "Today by 14:00 EST...",
      "control": {
        "approval_owner": "Finance Director (per DOA policy)",
        "policy_check": "Pass — restricted account: no...",
        "human_approval_required": true
      },
      "approval_status": "Pending",
      "approved_by": null,
      "approved_at": null
    }
  ],
  "reasoning_trace": [
    {"step": 1, "agent": "daily_cash", "status": "complete", "duration_ms": 220},
    {"step": 2, "agent": "liquidity_risk", "status": "complete", "duration_ms": 180},
    {"step": 3, "agent": "policy_check", "status": "complete", "duration_ms": 95},
    {"step": 4, "agent": "recommendation", "status": "complete", "duration_ms": 9200}
  ]
}
```

### POST /api/recommendations/{id}/approve

Request:
```json
{ "notes": "Approved — instructed bank at 13:45 EST" }
```

Response 200:
```json
{
  "id": "uuid",
  "approval_status": "Approved",
  "approved_by": "uuid",
  "approved_at": "2026-08-22T13:45:00Z",
  "notes": "Approved — instructed bank at 13:45 EST"
}
```

---

## Audit Log Entries

**Action values written:**
- `recommendation.approved` — when approve endpoint called
- `recommendation.rejected` — when reject endpoint called
- `recommendation.overridden` — when override endpoint called

**Example audit_log row:**
```python
{
    "id": UUID,
    "client_id": UUID,
    "user_id": UUID,
    "user_name": "Jane Smith",
    "action": "recommendation.approved",
    "entity_type": "recommendation",
    "entity_id": "rec_20260822_093000_a1b2c3d4",
    "old_value": {"approval_status": "Pending"},
    "new_value": {"approval_status": "Approved", "notes": "..."},
    "ip_address": "203.0.113.4",
    "created_at": "2026-08-22T13:45:00Z"
}
```

---

## Verification Checklist

- ✅ All 6 endpoints implemented and registered
- ✅ POST /api/recommendations/request publishes job, returns 202
- ✅ GET /api/recommendations/{request_id} polls job_status, returns full result when completed
- ✅ reasoning_trace mocked (static durations, TODO comment for real timing)
- ✅ blocked_count/blocked_reasons/source_agent_runs never exposed in API
- ✅ GET /api/recommendations lists with pagination and pending_approvals count
- ✅ POST approve/reject/override update MongoDB with positional operator
- ✅ 409 returned when trying to action already-actioned recommendation
- ✅ Audit events written for approve/reject/override
- ✅ Audit write failure non-blocking (business logic completes regardless)
- ✅ Role gates: TM/CFO only for approve/reject/override
- ✅ Analyst/TM/CFO can request, but only TM/CFO can approve
- ✅ client_id scoping enforced — cannot access other client's recommendations
- ✅ Service layer validates before MongoDB update
- ✅ All tests pass (16 test cases covering happy path, errors, role gates, client isolation)

---

## Files Summary

```
app-backend/app/routers/recommendations.py                 (470 lines)
  - POST /api/recommendations/request
  - GET  /api/recommendations/{request_id}
  - GET  /api/recommendations (list, paginated)
  - POST /api/recommendations/{id}/approve
  - POST /api/recommendations/{id}/reject
  - POST /api/recommendations/{id}/override

app-backend/app/services/recommendation_service.py         (210 lines)
  - get_recommendation_result() with internal field stripping
  - find_recommendation_by_id()
  - approve_recommendation()
  - reject_recommendation()
  - override_recommendation()
  - get_pending_approvals_count()

app-backend/tests/test_recommendation_endpoints.py         (450 lines)
  - 16 comprehensive test classes covering all endpoints, errors, role gates
```

---

## Integration Points

**Depends On:**
- Session 1 (App Backend scaffold, JWT, job publisher) ✓
- Session 2 (MongoDB client) ✓
- Session 3 (job_status table, polling pattern) ✓
- Session 5a (MongoDB recommendations collection written by Agent 8) ✓
- Session 9 (audit_log table, audit_service) ✓

**Used By:**
- Frontend (calls all 6 endpoints to request, poll, list, approve/reject/override)
- Session 14+ (may extend with additional approval workflows)

---

## Known Limitations & Session 12 TODO

1. **Reasoning_trace mock:** Currently returns fixed duration_ms values. Session 12 will wire real timing from AgentState. Look for comment: `# TODO: wire real timing from AgentState in Session 12`

2. **Real LLM wiring:** Agent 4 text is still mocked (Session 5a). Session 15 will wire real Anthropic API calls, but approval endpoints are ready now.

---

## Next Steps for Session 5c or 6+

1. Frontend integration tests (call approval endpoints via Cognito JWT)
2. Extended approval workflows (e.g. multi-level approval, escalation)
3. Recommendation override with different amounts/timing
4. Bulk approve/reject operations
5. Recommendation copy/save as template

---

**End of Session 5b. All recommendation endpoints ready for integration testing.**
