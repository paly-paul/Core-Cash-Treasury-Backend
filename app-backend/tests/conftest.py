import asyncio
import os
from typing import AsyncGenerator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Set environment variables before importing app config
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB_NAME", "test-core-cash")
os.environ.setdefault("SQS_QUEUE_URL", "http://localhost:9324/queue/test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("COGNITO_REGION", "us-east-1")
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_test123")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-client-id")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-key")

from app.database import Base
from app.models.client import Client
from app.models.legal_entity import LegalEntity
from app.models.bank import Bank
from app.models.account import Account
from app.models.users import Users


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Create test data
        client_id = uuid4()
        user_id = uuid4()

        client = Client(id=client_id, name="Test Client", slug="test-client")
        session.add(client)

        user = Users(id=user_id, email="test@example.com", client_id=client_id, role="Analyst")
        session.add(user)

        us_hq = LegalEntity(id=uuid4(), client_id=client_id, name="US HQ", base_currency="USD")
        uk_ops = LegalEntity(id=uuid4(), client_id=client_id, name="UK Operations", base_currency="GBP")
        eu_entity = LegalEntity(id=uuid4(), client_id=client_id, name="EU Entity", base_currency="EUR")
        apac_hub = LegalEntity(id=uuid4(), client_id=client_id, name="APAC Hub", base_currency="SGD")

        session.add_all([us_hq, uk_ops, eu_entity, apac_hub])

        bank = Bank(id=uuid4(), name="JPMorgan")
        session.add(bank)

        jpm_usd = Account(
            id=uuid4(), client_id=client_id, entity_id=us_hq.id, account_name="JPM USD Main",
            currency="USD", min_threshold=1000000, is_active=True
        )
        barclays_gbp = Account(
            id=uuid4(), client_id=client_id, entity_id=uk_ops.id, account_name="Barclays GBP Ops",
            currency="GBP", min_threshold=500000, is_active=True
        )
        bofa_eur = Account(
            id=uuid4(), client_id=client_id, entity_id=eu_entity.id, account_name="BofA EUR Reserve",
            currency="EUR", min_threshold=500000, is_active=True
        )
        eur_od = Account(
            id=uuid4(), client_id=client_id, entity_id=eu_entity.id, account_name="EUR OD Test",
            currency="EUR", min_threshold=200000, is_active=True
        )

        session.add_all([jpm_usd, barclays_gbp, bofa_eur, eur_od])

        await session.commit()

        yield session
