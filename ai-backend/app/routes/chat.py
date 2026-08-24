import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from core_cash_shared.schemas.chat import ChatRequest, ChatMessage
from app.auth.dependencies import get_current_user
from app.mongo.client import get_mongo_db
from app.database import get_db
from app.services.chat_context import load_chat_context
from app.services.chat_prompt import build_system_prompt
from app.services.mock_llm import mock_stream_response

router = APIRouter()


async def event_generator(
    chat_request: ChatRequest,
    current_user: dict,
    mongo_db,
    pg_db,
):
    """Generator for SSE events."""
    try:
        if not chat_request.messages or len(chat_request.messages) == 0:
            yield f"event: error\ndata: Messages list cannot be empty\n\n"
            return

        if chat_request.messages[-1].role != "user":
            yield f"event: error\ndata: Last message must be from user\n\n"
            return

        client_id = current_user.get("user_id", "")
        entity_id = chat_request.entity_id

        context = await load_chat_context(client_id, entity_id, mongo_db, pg_db)

        yield f"event: context\ndata: {json.dumps(context)}\n\n"

        system_prompt = build_system_prompt(context)

        async for token in mock_stream_response(chat_request.messages, system_prompt):
            yield f"event: token\ndata: {token}\n\n"

        yield f"event: done\ndata: done\n\n"

    except Exception as e:
        yield f"event: error\ndata: {str(e)}\n\n"


@router.post("/stream")
async def chat_stream(
    chat_request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    mongo_db=Depends(get_mongo_db),
    pg_db=Depends(get_db),
):
    """POST /chat/stream - SSE endpoint for chat."""
    if not chat_request.messages or len(chat_request.messages) == 0:
        raise HTTPException(status_code=422, detail="Messages list cannot be empty")

    if chat_request.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="Last message must be from user")

    return EventSourceResponse(
        event_generator(chat_request, current_user, mongo_db, pg_db),
        media_type="text/event-stream",
    )
