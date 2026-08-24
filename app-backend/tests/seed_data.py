"""
Seed test data into PostgreSQL and MongoDB for integration tests.
Run this once before starting integration tests.
"""
import asyncio
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.models.client import Client
from app.models.legal_entity import LegalEntity
from app.models.bank_account import BankAccount
from app.models.bank_statement import BankStatement
from app.models.manual_assumption import ManualAssumption
from app.models.investment_policy import InvestmentPolicy
from app.models.user import User
from app.models.user_role import UserRole


async def seed_data():
    """Seed test data."""
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/core_cash_test")
    engine = create_async_engine(db_url, echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        # 1. Create Client
        client = Client(
            id="client-test-001",
            name="Test Corp",
        )
        db.add(client)
        await db.commit()
        print("✓ Created client: client-test-001")

        # 2. Create Entity
        entity = LegalEntity(
            id="entity-test-001",
            client_id="client-test-001",
            name="Test Corp UK",
            currency="GBP",
        )
        db.add(entity)
        await db.commit()
        print("✓ Created entity: entity-test-001")

        # 3. Create BankAccount
        account = BankAccount(
            id="acct-001",
            entity_id="entity-test-001",
            account_number="GB29NWBK60161331926819",
            account_name="Main Operating",
            currency="GBP",
            min_threshold=500000,
            od_limit=2000000,
            od_utilised_amount=200000,
            include_in_cash_position=True,
        )
        db.add(account)
        await db.commit()
        print("✓ Created bank account: acct-001")

        # 4. Create BankStatements (5 rows, last 5 days)
        today = date.today()
        statements = [
            BankStatement(
                transaction_date=today - timedelta(days=4),
                credit_amount=Decimal("1000000"),
                debit_amount=None,
                currency="GBP",
                balance_after=Decimal("1000000"),
                account_id="acct-001",
                entity_id="entity-test-001",
                client_id="client-test-001",
            ),
            BankStatement(
                transaction_date=today - timedelta(days=3),
                credit_amount=None,
                debit_amount=Decimal("200000"),
                currency="GBP",
                balance_after=Decimal("800000"),
                account_id="acct-001",
                entity_id="entity-test-001",
                client_id="client-test-001",
            ),
            BankStatement(
                transaction_date=today - timedelta(days=2),
                credit_amount=Decimal("500000"),
                debit_amount=None,
                currency="GBP",
                balance_after=Decimal("1300000"),
                account_id="acct-001",
                entity_id="entity-test-001",
                client_id="client-test-001",
            ),
            BankStatement(
                transaction_date=today - timedelta(days=1),
                credit_amount=None,
                debit_amount=Decimal("100000"),
                currency="GBP",
                balance_after=Decimal("1200000"),
                account_id="acct-001",
                entity_id="entity-test-001",
                client_id="client-test-001",
            ),
            BankStatement(
                transaction_date=today,
                credit_amount=Decimal("250000"),
                debit_amount=None,
                currency="GBP",
                balance_after=Decimal("1450000"),
                account_id="acct-001",
                entity_id="entity-test-001",
                client_id="client-test-001",
            ),
        ]
        for stmt in statements:
            db.add(stmt)
        await db.commit()
        print("✓ Created 5 bank statements")

        # 5. Create ManualAssumptions (3 rows)
        assumptions = [
            ManualAssumption(
                entity_id="entity-test-001",
                client_id="client-test-001",
                date=today + timedelta(days=5),
                amount=Decimal("300000"),
                currency="USD",
                direction="Inflow",
                category="AR_COLLECTION",
                confidence_pct=Decimal("80"),
                description="Expected client payment",
                deleted_at=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            ),
            ManualAssumption(
                entity_id="entity-test-001",
                client_id="client-test-001",
                date=today + timedelta(days=5),
                amount=Decimal("150000"),
                currency="USD",
                direction="Outflow",
                category="AP_PAYMENT",
                confidence_pct=Decimal("60"),
                description="Supplier payment",
                deleted_at=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            ),
            ManualAssumption(
                entity_id="entity-test-001",
                client_id="client-test-001",
                date=today + timedelta(days=10),
                amount=Decimal("50000"),
                currency="USD",
                direction="Outflow",
                category="PAYROLL",
                confidence_pct=Decimal("30"),
                description="Low confidence payroll estimate",
                deleted_at=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            ),
        ]
        for assumption in assumptions:
            db.add(assumption)
        await db.commit()
        print("✓ Created 3 manual assumptions")

        # 6. Create InvestmentPolicy
        policy = InvestmentPolicy(
            entity_id="entity-test-001",
            client_id="client-test-001",
            max_single_counterparty_pct=Decimal("40"),
            max_tenor_days=90,
            min_rating="BBB",
            is_active=True,
        )
        db.add(policy)
        await db.commit()
        print("✓ Created investment policy")

        # 7. Create User
        user = User(
            id="user-test-001",
            client_id="client-test-001",
            email="treasurer@testcorp.com",
        )
        db.add(user)
        await db.commit()
        print("✓ Created user: treasurer@testcorp.com")

        # 8. Create UserRole
        user_role = UserRole(
            user_id="user-test-001",
            role="TreasuryManager",
        )
        db.add(user_role)
        await db.commit()
        print("✓ Assigned TreasuryManager role")

    await engine.dispose()
    print("\n✓ All test data seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed_data())
