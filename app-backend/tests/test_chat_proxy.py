import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from core_cash_shared.schemas.chat import ChatRequest, ChatMessage


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def valid_jwt_token():
    """Create a mock JWT token."""
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0LXVzZXIiLCJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJjb2duaXRvOmdyb3VwcyI6WyJWaWV3ZXIiXX0.test"


def test_chat_proxy_requires_auth(client):
    """Test that chat proxy requires authentication."""
    chat_request = {
        "messages": [{"role": "user", "content": "Hello"}]
    }
    response = client.post("/api/chat/stream", json=chat_request)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_chat_proxy_forwards_auth_header():
    """Test that chat proxy forwards Authorization header to AI Backend."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_bytes = AsyncMock(return_value=iter([b"test"]))
        mock_client.post.return_value = mock_response

        mock_client_class.return_value = mock_client

        with patch("app.routers.chat_proxy.get_current_user") as mock_get_user:
            mock_get_user.return_value = {
                "user_id": "test-user",
                "email": "test@example.com",
                "role": "Viewer",
            }

            from app.routers.chat_proxy import router
            from fastapi import Request, Depends
            from unittest.mock import Mock

            chat_request = ChatRequest(
                messages=[ChatMessage(role="user", content="Hello")]
            )

            request = Mock(spec=Request)
            request.headers = {"Authorization": "Bearer test-token"}

            current_user = {
                "user_id": "test-user",
                "email": "test@example.com",
                "role": "Viewer",
            }

            await router.routes[0].endpoint(
                request, chat_request, current_user
            )

            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args[1]
            assert "headers" in call_kwargs
            assert call_kwargs["headers"]["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_chat_proxy_ai_backend_unavailable():
    """Test chat proxy when AI Backend is unavailable."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = Exception("Connection refused")

        mock_client_class.return_value = mock_client

        with patch("app.routers.chat_proxy.get_current_user") as mock_get_user:
            mock_get_user.return_value = {
                "user_id": "test-user",
                "email": "test@example.com",
                "role": "Viewer",
            }

            from app.routers.chat_proxy import router
            from fastapi import Request

            chat_request = ChatRequest(
                messages=[ChatMessage(role="user", content="Hello")]
            )

            request = Mock(spec=Request)
            request.headers = {}

            current_user = {
                "user_id": "test-user",
                "email": "test@example.com",
                "role": "Viewer",
            }

            response = await router.routes[0].endpoint(
                request, chat_request, current_user
            )

            assert response.status_code == 500


@pytest.mark.asyncio
async def test_chat_proxy_handles_non_200_response():
    """Test chat proxy handles non-200 response from AI Backend."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_client.post.return_value = mock_response

        mock_client_class.return_value = mock_client

        with patch("app.routers.chat_proxy.get_current_user") as mock_get_user:
            mock_get_user.return_value = {
                "user_id": "test-user",
                "email": "test@example.com",
                "role": "Viewer",
            }

            from app.routers.chat_proxy import router
            from fastapi import Request

            chat_request = ChatRequest(
                messages=[ChatMessage(role="user", content="Hello")]
            )

            request = Mock(spec=Request)
            request.headers = {}

            current_user = {
                "user_id": "test-user",
                "email": "test@example.com",
                "role": "Viewer",
            }

            response = await router.routes[0].endpoint(
                request, chat_request, current_user
            )

            assert response.status_code == 503
