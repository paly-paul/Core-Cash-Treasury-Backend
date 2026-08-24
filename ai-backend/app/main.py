from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, verify_read_only
from app.mongo.client import mongo_client
from app.routes import health, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await verify_read_only()
    except Exception as e:
        raise RuntimeError(f"Failed to verify read-only database: {e}")

    try:
        await mongo_client.connect()
    except Exception as e:
        raise RuntimeError(f"Failed to connect to MongoDB: {e}")

    yield

    # Shutdown
    await mongo_client.disconnect()
    await engine.dispose()


app = FastAPI(title="Core Cash AI Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    from core_cash_shared.schemas.errors import ErrorDetail, ErrorResponse

    return ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_ERROR",
            message=str(exc),
            severity="error",
        )
    )


app.include_router(health.router)
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
