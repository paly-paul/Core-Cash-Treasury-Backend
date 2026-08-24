import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from core_cash_shared.schemas.chat import ChatRequest
from app.auth.dependencies import get_current_user
from app.auth.models import UserModel
from app.config import settings

router = APIRouter()


@router.post("/stream")
async def chat_stream_proxy(
    request: Request,
    chat_request: ChatRequest,
    current_user: UserModel = Depends(get_current_user),
):
    """POST /api/chat/stream - Proxy SSE stream from AI Backend."""
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            auth_header = request.headers.get("Authorization", "")
            headers = {}
            if auth_header:
                headers["Authorization"] = auth_header

            ai_backend_response = await client.post(
                f"{settings.ai_backend_url}/chat/stream",
                json=chat_request.model_dump(),
                headers=headers,
                stream=True,
            )

            if ai_backend_response.status_code != 200:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": {
                            "code": "CHAT_SERVICE_UNAVAILABLE",
                            "message": "Chat service temporarily unavailable.",
                            "severity": "error",
                        }
                    },
                )

            return StreamingResponse(
                ai_backend_response.aiter_bytes(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "CHAT_SERVICE_UNAVAILABLE",
                    "message": "Chat service temporarily unavailable.",
                    "severity": "error",
                }
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                    "severity": "error",
                }
            },
        )
