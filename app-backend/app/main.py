from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, AsyncSessionLocal
from app.mongo.client import mongo_client
from app.routes import health, accounts, entities, config, jobs, files
from app.utils.fixtures import load_fixtures


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda x: None)
    except Exception as e:
        raise RuntimeError(f"Failed to connect to PostgreSQL: {e}")

    try:
        await mongo_client.connect()
    except Exception as e:
        raise RuntimeError(f"Failed to connect to MongoDB: {e}")

    # Load fixtures
    async with AsyncSessionLocal() as db:
        await load_fixtures(db)

    yield

    # Shutdown
    await mongo_client.disconnect()
    await engine.dispose()


app = FastAPI(title="Core Cash App Backend", version="1.0.0", lifespan=lifespan)

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
app.include_router(accounts.router)
app.include_router(entities.router)
app.include_router(config.router)
app.include_router(jobs.router)
app.include_router(files.router)
