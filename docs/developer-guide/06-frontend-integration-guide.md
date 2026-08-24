# Frontend Integration Guide

This guide is written for **frontend developers integrating with Core Cash App Backend (port 8000)**.

**Rule #1**: Never call AI Backend (port 8001) directly. All requests go through App Backend.

---

## 1. Authentication

### Obtaining a JWT Token

1. **Redirect to Cognito**: User clicks "Login"
   ```javascript
   const loginUrl = new URL('https://cognito-idp.{region}.amazonaws.com/oauth2/authorize');
   loginUrl.searchParams.set('client_id', COGNITO_CLIENT_ID);
   loginUrl.searchParams.set('response_type', 'code');
   loginUrl.searchParams.set('scope', 'openid profile email');
   loginUrl.searchParams.set('redirect_uri', `${window.location.origin}/auth/callback`);
   window.location.href = loginUrl.toString();
   ```

2. **Exchange Authorization Code for JWT**: In callback handler
   ```javascript
   async function handleAuthCallback(code) {
     const response = await fetch('https://cognito-idp.{region}.amazonaws.com/oauth2/token', {
       method: 'POST',
       headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
       body: new URLSearchParams({
         grant_type: 'authorization_code',
         code,
         client_id: COGNITO_CLIENT_ID,
         redirect_uri: `${window.location.origin}/auth/callback`
       })
     });
     const { access_token, id_token } = await response.json();
     localStorage.setItem('access_token', id_token);  // Use id_token for App Backend
     return id_token;
   }
   ```

3. **Refresh Expiring Tokens**:
   ```javascript
   async function refreshToken(refreshToken) {
     const response = await fetch('https://cognito-idp.{region}.amazonaws.com/oauth2/token', {
       method: 'POST',
       headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
       body: new URLSearchParams({
         grant_type: 'refresh_token',
         refresh_token: refreshToken,
         client_id: COGNITO_CLIENT_ID
       })
     });
     const { access_token } = await response.json();
     localStorage.setItem('access_token', access_token);
     return access_token;
   }
   ```

### Passing the Token to API

**Every API request** includes:

```javascript
const headers = {
  'Authorization': `Bearer ${token}`,  // id_token or access_token from Cognito
  'Content-Type': 'application/json'
};

const response = await fetch(
  'http://localhost:8000/api/cash-position/request',
  {
    method: 'POST',
    headers,
    body: JSON.stringify({...})
  }
);
```

### Decoding JWT Claims

```javascript
function decodeToken(token) {
  const parts = token.split('.');
  const payload = JSON.parse(atob(parts[1]));
  return payload;
}

const claims = decodeToken(localStorage.getItem('access_token'));
console.log(claims.email);  // User email
console.log(claims['cognito:groups']);  // ["TreasuryManager", ...]
```

### Token Expiry & Handling

```javascript
async function ensureValidToken() {
  const token = localStorage.getItem('access_token');
  if (!token) {
    redirectToLogin();
    return null;
  }

  const claims = decodeToken(token);
  const expiresIn = (claims.exp * 1000) - Date.now();

  if (expiresIn < 5 * 60 * 1000) {  // Less than 5 minutes
    try {
      await refreshToken(localStorage.getItem('refresh_token'));
    } catch (err) {
      redirectToLogin();
      return null;
    }
  }

  return localStorage.getItem('access_token');
}
```

### Role-Based UI

**Display UI elements based on Cognito group membership**:

```javascript
const claims = decodeToken(token);
const roles = claims['cognito:groups'] || [];

const canApprove = roles.includes('TreasuryManager') || roles.includes('CFO');
const canUploadFiles = roles.includes('Analyst') || roles.includes('TreasuryManager') || roles.includes('CFO');
const canViewAudit = true;  // All roles

// Conditional rendering
{canApprove && <button onClick={approveRecommendation}>Approve</button>}
{!canApprove && <p>Only Treasury Managers and CFOs can approve.</p>}
```

| Role | Can Approve | Can Request | Can Upload | Can View |
|------|-------------|-------------|-----------|----------|
| Viewer | ❌ | ❌ | ❌ | ✅ |
| Analyst | ❌ | ✅ | ✅ | ✅ |
| TreasuryManager | ✅ | ✅ | ✅ | ✅ |
| CFO | ✅ | ✅ | ✅ | ✅ |

---

## 2. Async Request Pattern

Many endpoints follow a **POST → 202 (async job) → GET poll → result** pattern.

### Example: Request Forecast

```javascript
async function requestForecast() {
  // Step 1: Send POST request
  const response = await fetch(
    'http://localhost:8000/api/forecast/request',
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        horizon_days: 30,
        cash_position_date: new Date().toISOString().split('T')[0]
      })
    }
  );

  if (response.status !== 202) {
    throw new Error(`Unexpected status: ${response.status}`);
  }

  const { forecast_id, queued_at } = await response.json();
  console.log(`Forecast job queued: ${forecast_id}`);

  // Step 2: Poll for result
  return pollForecaseResult(forecast_id);
}

async function pollForecastResult(forecastId) {
  const maxRetries = 60;  // 60 × 2s = 120s timeout
  let retries = 0;

  while (retries < maxRetries) {
    const response = await fetch(
      `http://localhost:8000/api/forecast/${forecastId}`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      }
    );

    if (response.status === 404) {
      throw new Error('Forecast job not found');
    }

    if (response.status === 500) {
      throw new Error('Server error');
    }

    const data = await response.json();

    // Check result status
    if (data.status === 'completed') {
      console.log('Forecast ready:', data);
      return data;  // Success!
    }

    if (data.status === 'failed') {
      throw new Error(`Forecast failed: ${data.error}`);
    }

    // Still processing (status=queued or processing)
    console.log(`Still processing... (${retries + 1}/${maxRetries})`);
    await sleep(2000);  // Wait 2 seconds
    retries++;
  }

  throw new Error('Forecast request timeout after 120 seconds');
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
```

### Best Practices for Polling

```javascript
const POLL_INTERVAL = 2000;    // 2 seconds (recommended)
const MAX_TIMEOUT = 120000;    // 120 seconds (production timeout)
const MAX_RETRIES = MAX_TIMEOUT / POLL_INTERVAL;

async function pollWithExponentialBackoff(url, maxRetries = MAX_RETRIES) {
  let retries = 0;
  let backoff = POLL_INTERVAL;

  while (retries < maxRetries) {
    try {
      const response = await fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` }
      });

      const data = await response.json();
      if (data.status === 'completed' || data.status === 'failed') {
        return data;  // Done
      }

      // Still processing
      await sleep(backoff);
      backoff = Math.min(backoff * 1.5, 10000);  // Cap at 10 seconds
      retries++;
    } catch (err) {
      console.error(`Poll error (retry ${retries}):`, err);
      await sleep(backoff);
      retries++;
    }
  }

  throw new Error('Request timeout');
}
```

### Handling 202 Responses

| Status | Meaning | Action |
|--------|---------|--------|
| 202 | Job accepted and queued | Continue polling |
| 200 | Job completed | Retrieve and display result |
| 404 | Job not found | Show error; retry from start |
| 503 | Service overloaded | Show "retry later" message |
| 500 | Server error | Show error; contact support |

---

## 3. Chat SSE Integration

**Server-Sent Events (SSE)** for real-time, streaming chat responses.

### Basic Implementation

```javascript
async function streamChat(messages) {
  const response = await fetch(
    'http://localhost:8000/api/chat/stream',
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        messages: [
          { role: 'user', content: 'What is our 30-day cash forecast?' }
        ]
      })
    }
  );

  if (response.status !== 200) {
    throw new Error(`Chat error: ${response.status}`);
  }

  // Parse SSE stream
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let messageBuffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');

    // Keep last incomplete line in buffer
    buffer = lines[lines.length - 1];

    for (let i = 0; i < lines.length - 1; i++) {
      const line = lines[i].trim();

      if (line.startsWith('event: ')) {
        currentEvent = line.substring(7);
      } else if (line.startsWith('data: ')) {
        const data = line.substring(6);

        if (currentEvent === 'context') {
          // First event: treasury context snapshot
          const context = JSON.parse(data);
          updateSidebarData(context);
        } else if (currentEvent === 'token') {
          // Streaming text chunk
          messageBuffer += data;
          updateChatBubble(messageBuffer);
        } else if (currentEvent === 'done') {
          // Stream complete
          console.log('Chat response complete');
          stopSpinner();
        } else if (currentEvent === 'error') {
          // Error occurred
          const error = JSON.parse(data);
          showErrorMessage(error.message);
          stopSpinner();
        }
      }
    }
  }
}

// SSE event types
const events = {
  'context': {
    data: { total_balance_usd, risk_level, forecast_outlook: [...] },
    action: 'Update sidebar data panel with latest treasury snapshot'
  },
  'token': {
    data: 'string (one text chunk)',
    action: 'Append to chat message bubble; show spinner while receiving'
  },
  'done': {
    data: 'null',
    action: 'Stop spinner; mark message complete'
  },
  'error': {
    data: { error_code: '...', message: '...' },
    action: 'Show error state; stop spinner'
  }
};
```

### Advanced: EventSource API (Simpler)

```javascript
async function streamChatWithEventSource(prompt) {
  return new Promise((resolve, reject) => {
    // Fetch requires manual SSE parsing; EventSource is simpler for server-to-client only
    // (but doesn't support custom headers; use fetch + manual parsing for auth)

    // Stick with fetch + manual SSE parsing for authorization header support
    streamChat([{ role: 'user', content: prompt }])
      .then(resolve)
      .catch(reject);
  });
}
```

### UI Integration Example

```javascript
class ChatComponent extends React.Component {
  state = {
    messages: [],
    isStreaming: false,
    contextData: null,
    currentMessage: ''
  };

  async onSendMessage(prompt) {
    this.setState({ isStreaming: true, currentMessage: '' });

    try {
      await this.streamChat([
        { role: 'user', content: prompt }
      ]);
    } catch (err) {
      this.setState({
        messages: [...this.state.messages, {
          role: 'assistant',
          content: `Error: ${err.message}`
        }]
      });
    } finally {
      this.setState({ isStreaming: false });
    }
  }

  updateSidebarData(context) {
    this.setState({ contextData: context });
    // Trigger sidebar update with latest balances, risks, etc.
  }

  updateChatBubble(text) {
    this.setState({ currentMessage: text });
  }

  render() {
    const { messages, currentMessage, isStreaming, contextData } = this.state;
    return (
      <div className="chat-container">
        <aside className="sidebar">
          {contextData && (
            <div>
              <p>Cash: ${contextData.total_balance_usd?.toLocaleString()}</p>
              <p>Risk Level: {contextData.risk_level}</p>
            </div>
          )}
        </aside>
        <main className="chat">
          {messages.map((msg, i) => (
            <div key={i} className={`message ${msg.role}`}>
              {msg.content}
            </div>
          ))}
          {currentMessage && (
            <div className="message assistant">
              {currentMessage}
              {isStreaming && <span className="spinner">⏳</span>}
            </div>
          )}
        </main>
      </div>
    );
  }
}
```

---

## 4. Recommendation Approval Flow

### Step-by-Step Example

```javascript
async function showRecommendationApprovalFlow() {
  // 1. Fetch pending recommendations
  const recommendations = await fetchRecommendations('Pending');

  for (const rec of recommendations) {
    // 2. Display recommendation with details
    showRecommendationCard({
      id: rec.id,
      what: rec.what,
      why: rec.why,
      when: rec.when,
      control: rec.control,
      priority: rec.priority,
      approval_status: rec.approval_status
    });

    // 3. User clicks Approve or Reject
    const action = await waitForUserAction(rec.id);  // Returns "approve", "reject", or "override"

    if (action === 'approve') {
      // 4a. POST approval
      const result = await approveRecommendation(rec.id, {
        notes: document.getElementById('approval-notes').value
      });
      showSuccessMessage(`Approved: ${result.approval_status}`);

    } else if (action === 'reject') {
      // 4b. POST rejection
      const result = await rejectRecommendation(rec.id, {
        reason: document.getElementById('rejection-reason').value
      });
      showSuccessMessage(`Rejected: ${result.approval_status}`);

    } else if (action === 'override') {
      // 4c. POST override
      const result = await overrideRecommendation(rec.id, {
        action_taken: document.getElementById('override-action').value,
        notes: document.getElementById('override-notes').value
      });
      showSuccessMessage(`Overridden: ${result.approval_status}`);
    }
  }
}

async function approveRecommendation(recommendationId, body) {
  const response = await fetch(
    `http://localhost:8000/api/recommendations/${recommendationId}/approve`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    }
  );

  if (response.status === 409) {
    throw new Error('Recommendation has already been actioned.');
  }

  if (response.status !== 200) {
    throw new Error(`Failed to approve: ${response.status}`);
  }

  return await response.json();
}

async function rejectRecommendation(recommendationId, body) {
  const response = await fetch(
    `http://localhost:8000/api/recommendations/${recommendationId}/reject`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    }
  );

  if (response.status === 409) {
    throw new Error('Recommendation has already been actioned.');
  }

  return await response.json();
}

async function overrideRecommendation(recommendationId, body) {
  const response = await fetch(
    `http://localhost:8000/api/recommendations/${recommendationId}/override`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    }
  );

  if (response.status === 409) {
    throw new Error('Recommendation has already been actioned.');
  }

  return await response.json();
}
```

---

## 5. Key Business Rules for UI

**Frontend developers MUST enforce these rules** to ensure consistency with backend logic:

### Cash Position & Liquidity

- ❌ **Never add `od_headroom` to `usable_cash`**. They are separate figures.
  - `usable_cash` = sum of balances where `include_in_cash_position=true`
  - `od_headroom` = `od_limit - od_utilised_amount` (computed separately)
  - Example: Display as two separate cards: "Usable Cash: $5M" and "OD Headroom: $500K"

- ✅ **Warning threshold is always 70%** (never display 80% or allow configuration to go higher)
  - `is_warning = true` when `cash / required < 0.70`
  - Red alert when crossing this threshold

### Forecast & Variance

- ✅ **Variance tolerance is always ±5%**
  - Never display ±3%; always show ±5%
  - If frontend receives a different tolerance, ignore it and use ±5%

- ✅ **Show MTD change, never YTD**
  - Month-to-date balances preferred for treasury dashboard
  - If year-to-date data provided, transform to MTD for display

### Recommendations & Approvals

- ✅ **All recommendations show `approval_status`**
  - States: Pending, Approved, Rejected, Overridden, Blocked
  - Only Pending recs show action buttons (Approve, Reject, Override)

- ❌ **Never show `blocked_count` or `blocked_reasons` in UI**
  - These are internal Agent 7 fields
  - If `approval_status="Blocked"`, simply show "Blocked by policy" without details

- ✅ **Handle 409 Conflict gracefully**
  - If user clicks "Approve" but rec was already rejected by another user, show:
    - "Recommendation has already been actioned by [user] at [time]. Please refresh."

### Data Status Indicators

- 📊 **Show data_status for forecast & position**
  - `data_status="partial"`: ✅ Forecast calculated; some data may be missing
  - `data_status="blocked"`: ⛔ Cannot calculate; show "Upload bank data to unblock" message
  - `data_status="live"`: ✅ All required data available

### Chat & Recommendations

- 📖 **Chat is read-only; never suggest Claude can execute**
  - User message: "Invest the surplus"
  - Chat response: "[MOCK response about investing the surplus]"
  - UI must NOT show: "Executing investment now..."
  - Chat is for analysis and explanation only

---

## 6. Error Code Reference & UI Handling

| Code | HTTP | Meaning | UI Action |
|------|------|---------|-----------|
| `AUTH_TOKEN_MISSING` | 401 | No Authorization header | Redirect to login |
| `AUTH_TOKEN_INVALID` | 401 | JWT signature invalid | Show "Your session is invalid. Please log in again." |
| `AUTH_TOKEN_EXPIRED` | 401 | Token expired | Refresh token automatically; if refresh fails, redirect to login |
| `AUTH_PERMISSION_DENIED` | 403 | User lacks required role | Show "Access Denied. You do not have permission for this action." |
| `VALIDATION_REQUIRED_FIELD` | 422 | Missing field in request | Highlight form field; show "This field is required" |
| `VALIDATION_INVALID_FORMAT` | 422 | Field format wrong (e.g., date) | Highlight form field; show specific format (e.g., "Date must be YYYY-MM-DD") |
| `VALIDATION_FILE_TOO_LARGE` | 422 | File > 10 MB | Show "File is too large. Maximum size is 10 MB. Please upload a smaller file." |
| `VALIDATION_UNSUPPORTED_FORMAT` | 422 | File format not recognized | Show "File format not supported. Please upload CSV, BAI2, MT940, or camt.053." |
| `VALIDATION_MISSING_COLUMN` | 422 | Required CSV column missing | Show "CSV file is missing required column: [column_name]" |
| `VALIDATION_EMPTY_FILE` | 422 | File has no rows | Show "File is empty. Please upload a file with data." |
| `OPENING_BALANCE_UNRESOLVED` | 503 | No bank statement balance found | Show "Upload bank statement data to unblock forecast. Forecast requires a recent bank balance." |
| `FX_RATE_MISSING` | 422 | FX rate not configured | Show "FX rate for [currency] not set. Please configure FX rates." |
| `INVESTMENT_POLICY_NOT_UPLOADED` | 422 | No investment policy | Show "Investment policy not configured. Please upload policy first." |
| `JOB_NOT_FOUND` | 404 | Request ID not found | Show "Request not found. Please check the request ID and try again." |
| `JOB_STILL_PROCESSING` | 202 | Job still running | Show spinner; continue polling |
| `JOB_FAILED` | 500 | Agent error | Show "Analysis failed. Please try again or contact support." with "Retry" button |
| `DATA_STALE` | 422 | Data older than expected | Show "Data is stale. Please upload fresh bank data and retry." with "Upload" button |
| `AGENT_ERROR` | 503 | Queue publish failed | Show "Service temporarily unavailable. Please retry in a moment." with "Retry" button |
| `INTERNAL_ERROR` | 500 | Unhandled server error | Show "An unexpected error occurred. Please contact support with error ID: [request_id]" |

### Example Error Handling

```javascript
async function handleApiError(response, context = '') {
  const data = await response.json();
  const errorCode = data.error?.code || 'UNKNOWN_ERROR';
  const errorMessage = data.error?.message || 'An unexpected error occurred';

  switch (errorCode) {
    case 'AUTH_TOKEN_EXPIRED':
      redirectToLogin();
      break;

    case 'AUTH_PERMISSION_DENIED':
      showErrorDialog('Access Denied', 'You do not have permission for this action.');
      break;

    case 'OPENING_BALANCE_UNRESOLVED':
      showErrorDialog(
        'Forecast Blocked',
        'Upload a bank statement with a closing balance to unblock the forecast.',
        { action: 'Upload Bank Data', onClick: navigateToFileUpload }
      );
      break;

    case 'VALIDATION_FILE_TOO_LARGE':
      showErrorToast('File is too large (max 10 MB).');
      break;

    case 'JOB_FAILED':
      showErrorDialog(
        'Analysis Failed',
        errorMessage,
        { action: 'Retry', onClick: () => retryLastRequest() }
      );
      break;

    default:
      showErrorToast(`${context}: ${errorMessage}`);
  }
}
```

---

## Summary

### Key Points

1. **Always include JWT token** in every API request
2. **Use polling pattern** for async jobs (POST → 202 → GET poll)
3. **Parse SSE events** for real-time chat (event: context, token, done, error)
4. **Handle 409 Conflict** gracefully when recommendation already actioned
5. **Enforce business rules**: 70% warning, ±5% variance, ±never add od_headroom to usable_cash
6. **Hide internal fields**: Never show blocked_count, blocked_reasons
7. **Show data_status** for forecast & position (partial, blocked, live)
8. **No autonomous execution**: Chat is read-only analysis; treasury team approves all actions

### Quick Reference

| Task | Endpoint | Method | Status |
|------|----------|--------|--------|
| Request forecast | POST /api/forecast/request | POST | 202 (poll with GET) |
| Request recommendations | POST /api/recommendations/request | POST | 202 (poll with GET) |
| Approve recommendation | /api/recommendations/{id}/approve | POST | 200 (or 409 if already actioned) |
| Stream chat | POST /api/chat/stream | POST | 200 (SSE) |
| Get cash position | POST /api/cash-position/request | POST | 202 (poll with GET) |
| Upload file | POST /api/files/upload | POST (multipart) | 202 (poll with GET) |

---

**Next**: Refer to [API Endpoint Reference](03-api-reference.md) for complete endpoint documentation.

---

**For questions or issues**: Contact the Core Cash team or refer to [Configuration & Environment Variables](05-config-and-env.md) for troubleshooting.
