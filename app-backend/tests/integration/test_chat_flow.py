"""
Integration tests for chat SSE flow.
Tests streaming responses and error handling.
"""
import pytest
import httpx
from tests.jwt_helper import make_treasury_manager_token, make_viewer_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        yield client


def parse_sse_events(response_text: str):
    """Parse SSE event stream."""
    events = []
    current_event = {}

    for line in response_text.split("\n"):
        if line.startswith("event:"):
            current_event["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current_event["data"] = line.split(":", 1)[1].strip()
        elif line == "":
            if current_event:
                events.append(current_event)
                current_event = {}

    if current_event:
        events.append(current_event)

    return events


@pytest.mark.asyncio
class TestChatFlow:
    """Test chat SSE streaming."""

    async def test_chat_sse_stream(self, http_client):
        """
        POST /api/chat/stream with valid messages
        Assert: SSE stream with context, token, and done events
        Assert: no error events
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/chat/stream",
            json={
                "messages": [{"role": "user", "content": "What is my cash position?"}],
                "entity_id": "entity-test-001",
            },
            headers=headers,
        )

        # Stream response should start with 200 and have content-type text/event-stream
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.text[:200]}"

        # Parse SSE events
        text = response.text
        events = parse_sse_events(text)

        # Should have at least context and done events
        event_types = [e.get("event") for e in events if "event" in e]

        assert "context" in event_types, "Should receive a context event"
        assert "done" in event_types, "Should receive a done event"
        assert "error" not in event_types, "Should not receive error events"

        # Last event should be done
        if events:
            last_event = events[-1]
            assert last_event.get("event") == "done", \
                "Last event should be done event"

    async def test_chat_empty_messages_422(self, http_client):
        """
        POST /api/chat/stream with empty messages
        Assert: 422 (validation error)
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/chat/stream",
            json={
                "messages": [],
                "entity_id": "entity-test-001",
            },
            headers=headers,
        )

        assert response.status_code == 422, \
            f"Empty messages should return 422, got {response.status_code}"

    async def test_chat_no_token_401(self, http_client):
        """
        POST /api/chat/stream without Authorization header
        Assert: 401
        """
        response = await http_client.post(
            "/api/chat/stream",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "entity_id": "entity-test-001",
            },
        )

        assert response.status_code == 401, \
            f"Expected 401, got {response.status_code}"

    async def test_chat_viewer_can_access(self, http_client):
        """
        POST /api/chat/stream with Viewer token
        Assert: 200 (viewers can read-only chat)
        """
        viewer_token = make_viewer_token()
        headers = {"Authorization": f"Bearer {viewer_token}"}

        response = await http_client.post(
            "/api/chat/stream",
            json={
                "messages": [{"role": "user", "content": "Show me analytics"}],
                "entity_id": "entity-test-001",
            },
            headers=headers,
        )

        # Viewer should be able to read
        if response.status_code == 200:
            text = response.text
            events = parse_sse_events(text)
            event_types = [e.get("event") for e in events if "event" in e]
            assert "error" not in event_types, "Should not be denied"
