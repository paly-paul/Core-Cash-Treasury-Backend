import asyncio
from typing import AsyncGenerator
from core_cash_shared.schemas.chat import ChatMessage


async def mock_stream_response(
    messages: list[ChatMessage],
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """
    Mocked token-by-token streamer.
    In Session 12, replace with real Anthropic streaming client.
    Simulates ~50ms inter-token delay.
    """

    last_user_message = messages[-1].content.lower() if messages else ""

    if any(w in last_user_message for w in ["cash", "balance", "position"]):
        response = (
            "Based on the latest data, your usable cash position is as shown in the "
            "context. Review the active threshold breaches for entities approaching "
            "their minimum balance requirements."
        )
    elif any(w in last_user_message for w in ["risk", "breach", "alert"]):
        response = (
            "Your current liquidity risk score reflects the number of active threshold "
            "breaches and data freshness. I recommend reviewing the pending action "
            "recommendations — all require your approval before any action is taken."
        )
    elif any(w in last_user_message for w in ["recommend", "action", "suggest"]):
        response = (
            "There are pending recommendations awaiting your review. Each recommendation "
            "includes a 'Why', 'What', 'When', and 'Control' field. No action will be "
            "taken until a TreasuryManager or CFO approves."
        )
    elif any(w in last_user_message for w in ["forecast", "variance"]):
        response = (
            "Forecast and variance data will be available once the forecast engine "
            "is fully operational. Check back after the next scheduled forecast run."
        )
    else:
        response = (
            "I'm here to help with your treasury questions. You can ask me about "
            "your cash position, liquidity risk, threshold breaches, or pending "
            "recommendations."
        )

    words = response.split(" ")
    for i, word in enumerate(words):
        token = word if i == 0 else " " + word
        yield token
        await asyncio.sleep(0.05)
