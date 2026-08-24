import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from uuid import UUID
from typing import Optional

from app.services.audit_service import write_audit_event

logger = logging.getLogger(__name__)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs all state-changing requests (POST, PUT, PATCH, DELETE) to audit_log.
    This is a last-resort safety net. Individual service methods should call
    write_audit_event() directly for events where old_value/new_value context is available.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        if request.method in MUTATING_METHODS and 200 <= response.status_code < 300:
            try:
                from app.database import AsyncSessionLocal

                client_id: Optional[UUID] = None
                user_id: Optional[UUID] = None
                user_name: Optional[str] = None
                ip_address: Optional[str] = None

                if hasattr(request.state, "user"):
                    user = request.state.user
                    user_id = getattr(user, "user_id", None)
                    user_name = getattr(user, "email", None)
                    client_id = getattr(user, "client_id", None)

                if request.client:
                    ip_address = request.client.host

                if client_id:
                    async with AsyncSessionLocal() as db:
                        path = request.url.path
                        await write_audit_event(
                            db=db,
                            client_id=client_id,
                            user_id=user_id,
                            user_name=user_name,
                            action=f"{request.method.lower()}.{path}",
                            ip_address=ip_address,
                        )
            except Exception as e:
                logger.error(f"Audit middleware error: {e}", exc_info=True)

        return response
