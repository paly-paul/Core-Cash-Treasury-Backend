import pytest
from app.services.chat_prompt import build_system_prompt
from app.services.mock_llm import mock_stream_response
from core_cash_shared.schemas.chat import ChatMessage


@pytest.mark.asyncio
async def test_mock_streamer_produces_tokens():
    """Test that mock streamer produces tokens."""
    messages = [ChatMessage(role="user", content="What is my cash balance?")]
    system_prompt = "You are helpful"

    tokens = []
    async for token in mock_stream_response(messages, system_prompt):
        tokens.append(token)

    assert len(tokens) > 0
    assert all(isinstance(token, str) for token in tokens)
    joined = "".join(tokens)
    assert len(joined) > 0


@pytest.mark.asyncio
async def test_system_prompt_builder():
    """Test system prompt builder."""
    context = {
        "entity_name": "Acme Ltd",
        "cash_position": 5_000_000,
        "risk_level": "Medium",
        "risk_score": 5,
        "active_breaches": [{"id": "1"}],
        "pending_recommendations": [{"id": "a"}, {"id": "b"}],
    }
    prompt = build_system_prompt(context)

    assert "Acme Ltd" in prompt
    assert "5,000,000" in prompt
    assert "Medium" in prompt
    assert "1" in prompt
    assert "2" in prompt


@pytest.mark.asyncio
async def test_system_prompt_builder_empty_context():
    """Test system prompt builder with empty context."""
    context = {
        "entity_name": None,
        "cash_position": None,
        "risk_level": None,
        "risk_score": None,
        "active_breaches": [],
        "pending_recommendations": [],
    }
    prompt = build_system_prompt(context)

    assert "All entities" in prompt
    assert "unavailable" in prompt
    assert "unknown" in prompt


@pytest.mark.asyncio
async def test_mock_streamer_cash_question():
    """Test mock streamer with cash-related question."""
    messages = [ChatMessage(role="user", content="What is the cash position?")]
    system_prompt = "You are helpful"

    response_text = ""
    async for token in mock_stream_response(messages, system_prompt):
        response_text += token

    assert "cash position" in response_text.lower()


@pytest.mark.asyncio
async def test_mock_streamer_risk_question():
    """Test mock streamer with risk-related question."""
    messages = [ChatMessage(role="user", content="What is the risk level?")]
    system_prompt = "You are helpful"

    response_text = ""
    async for token in mock_stream_response(messages, system_prompt):
        response_text += token

    assert "liquidity risk" in response_text.lower() or "risk score" in response_text.lower()


@pytest.mark.asyncio
async def test_mock_streamer_recommendation_question():
    """Test mock streamer with recommendation question."""
    messages = [ChatMessage(role="user", content="What actions are recommended?")]
    system_prompt = "You are helpful"

    response_text = ""
    async for token in mock_stream_response(messages, system_prompt):
        response_text += token

    assert "recommendation" in response_text.lower()


@pytest.mark.asyncio
async def test_mock_streamer_generic_question():
    """Test mock streamer with generic question."""
    messages = [ChatMessage(role="user", content="Hello")]
    system_prompt = "You are helpful"

    response_text = ""
    async for token in mock_stream_response(messages, system_prompt):
        response_text += token

    assert len(response_text) > 0
    assert "question" in response_text.lower() or "help" in response_text.lower()
