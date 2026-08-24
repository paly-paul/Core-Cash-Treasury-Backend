from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, future=True
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def verify_read_only():
    """Verify the database connection is read-only."""
    async with engine.begin() as conn:
        try:
            await conn.run_sync(
                lambda x: x.execute("INSERT INTO client (name,slug) VALUES ('test','test')")
            )
            raise RuntimeError(
                "AI Backend DB user must be read-only — INSERT succeeded"
            )
        except Exception:
            pass
