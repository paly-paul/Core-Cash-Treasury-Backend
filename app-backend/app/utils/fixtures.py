"""
Idempotent fixture loader for demo data.
Safe to run multiple times without creating duplicates.
"""
from decimal import Decimal
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.legal_entity import LegalEntity
from app.models.bank import Bank
from app.models.users import Users
from app.models.account import Account
from app.models.statement import Statement
from app.models.fx_rates import FXRate
from app.models.ar_data import ARData
from app.models.source_file import SourceFile


async def load_fixtures(db: AsyncSession):
    """Load demo fixtures if not already present. Idempotent."""

    # Check if fixtures already loaded (client "Core Demo" exists)
    existing_client = await db.execute(
        select(Client).where(Client.slug == "core-demo")
    )
    if existing_client.scalar():
        return

    # Create client
    client = Client(name="Core Demo", slug="core-demo")
    db.add(client)
    await db.flush()
    client_id = client.id

    # Create legal entities
    entities = {
        "US HQ": ("USD", "US"),
        "UK Operations": ("GBP", "GB"),
        "EU Entity": ("EUR", "DE"),
        "APAC Hub": ("SGD", "SG"),
    }
    entity_map = {}
    for name, (currency, country) in entities.items():
        entity = LegalEntity(
            client_id=client_id, name=name, base_currency=currency, country_code=country
        )
        db.add(entity)
        await db.flush()
        entity_map[name] = entity.id

    # Create banks
    banks = {}
    for bank_name in ["JPMorgan", "Barclays"]:
        bank = Bank(client_id=client_id, name=bank_name, swift_code=None)
        db.add(bank)
        await db.flush()
        banks[bank_name] = bank.id

    # Create users
    users_data = [
        ("viewer@demo.com", "Viewer"),
        ("analyst@demo.com", "Analyst"),
        ("treasury@demo.com", "TreasuryManager"),
    ]
    for email, role in users_data:
        user = Users(client_id=client_id, email=email, role=role)
        db.add(user)

    await db.flush()

    # Create accounts
    accounts_spec = [
        {
            "name": "JPM USD Main",
            "entity": "US HQ",
            "bank": "JPMorgan",
            "currency": "USD",
            "min_threshold": Decimal("2000000"),
            "restricted": False,
            "od_limit": None,
            "refresh_frequency": "Daily",
            "include_in_cash": True,
        },
        {
            "name": "Barclays GBP Ops",
            "entity": "UK Operations",
            "bank": "Barclays",
            "currency": "GBP",
            "min_threshold": Decimal("500000"),
            "restricted": False,
            "od_limit": None,
            "refresh_frequency": "Daily",
            "include_in_cash": True,
        },
        {
            "name": "BofA EUR Reserve",
            "entity": "EU Entity",
            "bank": None,
            "currency": "EUR",
            "min_threshold": Decimal("500000"),
            "restricted": False,
            "od_limit": Decimal("500000"),
            "refresh_frequency": "Daily",
            "include_in_cash": True,
        },
        {
            "name": "JPM USD Restricted",
            "entity": "US HQ",
            "bank": "JPMorgan",
            "currency": "USD",
            "min_threshold": Decimal("0"),
            "restricted": True,
            "od_limit": None,
            "refresh_frequency": "Manual",
            "include_in_cash": True,
        },
        {
            "name": "SGD Petty Cash",
            "entity": "APAC Hub",
            "bank": None,
            "currency": "SGD",
            "min_threshold": Decimal("0"),
            "restricted": False,
            "od_limit": None,
            "refresh_frequency": "Weekly",
            "include_in_cash": False,
        },
        {
            "name": "EUR OD Test",
            "entity": "EU Entity",
            "bank": None,
            "currency": "EUR",
            "min_threshold": Decimal("200000"),
            "restricted": False,
            "od_limit": Decimal("500000"),
            "refresh_frequency": "Daily",
            "include_in_cash": True,
        },
    ]

    account_map = {}
    for spec in accounts_spec:
        account = Account(
            client_id=client_id,
            entity_id=entity_map[spec["entity"]],
            bank_id=banks.get(spec["bank"]),
            account_name=spec["name"],
            currency=spec["currency"],
            min_threshold=spec["min_threshold"],
            restricted_flag=spec["restricted"],
            od_limit=spec["od_limit"],
            refresh_frequency=spec["refresh_frequency"],
            include_in_cash_position=spec["include_in_cash"],
            is_active=True,
        )
        db.add(account)
        await db.flush()
        account_map[spec["name"]] = account.id

    await db.flush()

    # Create statements (dated yesterday)
    yesterday = date.today() - timedelta(days=1)
    statements_spec = [
        ("JPM USD Main", Decimal("7200000"), Decimal("7200000")),
        ("Barclays GBP Ops", Decimal("2700000"), Decimal("2700000")),
        ("BofA EUR Reserve", Decimal("430000"), Decimal("430000")),  # BREACH
        ("JPM USD Restricted", Decimal("3400000"), Decimal("3400000")),
        ("SGD Petty Cash", Decimal("15000"), Decimal("15000")),
        ("EUR OD Test", Decimal("-50000"), Decimal("0")),  # OD test
    ]

    for name, closing, available in statements_spec:
        account = await db.execute(
            select(Account).where(Account.account_name == name)
        )
        acc_obj = account.scalar()
        if acc_obj:
            stmt = Statement(
                account_id=acc_obj.id,
                statement_date=yesterday,
                closing_balance=closing,
                available_balance=available,
                currency=acc_obj.currency,
                source="fixture",
            )
            db.add(stmt)

            # Set od_utilised_amount for EUR OD Test
            if name == "EUR OD Test":
                acc_obj.od_utilised_amount = Decimal("50000")

    # Create FX rates (today's date)
    today = date.today()
    fx_rates_spec = [
        ("GBP", Decimal("1.2700")),
        ("EUR", Decimal("1.0850")),
        ("SGD", Decimal("0.7400")),
    ]

    viewer_user = await db.execute(
        select(Users).where(Users.email == "viewer@demo.com")
    )
    viewer_id = viewer_user.scalar().id

    for currency_from, rate in fx_rates_spec:
        fx = FXRate(
            client_id=client_id,
            currency_from=currency_from,
            currency_to="USD",
            rate=rate,
            rate_date=today,
            entered_by=viewer_id,
        )
        db.add(fx)

    await db.flush()

    # Create source file for AR data
    source_file = SourceFile(
        client_id=client_id,
        file_name="ar_fixture.csv",
        file_type="csv",
        upload_type="ar",
        status="Processed",
        rows_received=5,
        rows_valid=5,
        rows_failed=0,
        user_id=viewer_id,
    )
    db.add(source_file)
    await db.flush()

    # Create AR data for concentration risk testing
    # Top 3 share: (340k + 210k + 140k*1.27) / total ≈ 69% → just below 70% threshold
    ar_fixtures = [
        {
            "counterparty_name": "Customer A",
            "amount_local": Decimal("340000"),
            "currency": "USD",
            "amount_usd": Decimal("340000"),
            "entity_id": entity_map["US HQ"],
            "status": "Open",
        },
        {
            "counterparty_name": "GlobalTech Ltd",
            "amount_local": Decimal("210000"),
            "currency": "USD",
            "amount_usd": Decimal("210000"),
            "entity_id": entity_map["US HQ"],
            "status": "Open",
        },
        {
            "counterparty_name": "Nordic AS",
            "amount_local": Decimal("140000"),
            "currency": "GBP",
            "amount_usd": Decimal("177800"),  # 140000 * 1.27
            "entity_id": entity_map["UK Operations"],
            "status": "Overdue",
        },
        {
            "counterparty_name": "Acme Corp",
            "amount_local": Decimal("180000"),
            "currency": "USD",
            "amount_usd": Decimal("180000"),
            "entity_id": entity_map["US HQ"],
            "status": "Open",
        },
        {
            "counterparty_name": "Beta GmbH",
            "amount_local": Decimal("130000"),
            "currency": "EUR",
            "amount_usd": Decimal("141050"),  # 130000 * 1.085
            "entity_id": entity_map["EU Entity"],
            "status": "Open",
        },
    ]

    for ar_spec in ar_fixtures:
        ar = ARData(
            client_id=client_id,
            source_file_id=source_file.id,
            counterparty_name=ar_spec["counterparty_name"],
            currency=ar_spec["currency"],
            amount_local=ar_spec["amount_local"],
            amount_usd=ar_spec["amount_usd"],
            entity_id=ar_spec["entity_id"],
            status=ar_spec["status"],
        )
        db.add(ar)

    await db.commit()
