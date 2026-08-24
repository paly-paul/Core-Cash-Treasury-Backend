"""Agent 1: Daily Cash Position

Deterministic agent that produces consolidated cash position across all entities,
banks, and currencies. Reads from PostgreSQL, writes to MongoDB.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.state import AgentState


async def run_agent_1_cash_position(state: AgentState) -> AgentState:
    """Run Daily Cash Position Agent."""
    try:
        from app.database import AsyncSessionLocal
        from app.mongo.client import get_mongo_db

        # Get database connections
        async with AsyncSessionLocal() as db:
            mongo_db = get_mongo_db()
            output = await compute_cash_position(
                db=db, mongo_db=mongo_db, state=state
            )
            state["cash_position"] = output
            return state

    except Exception as e:
        state["errors"]["agent_1"] = str(e)
        return state


async def compute_cash_position(db: AsyncSession, mongo_db, state: AgentState) -> Dict[str, Any]:
    """Compute consolidated cash position from PostgreSQL data."""
    from app.models.account import Account
    from app.models.statement import Statement
    from app.models.legal_entity import LegalEntity
    from app.models.fx_rates import FXRate

    client_id = state["client_id"]
    run_id = str(uuid4())
    as_of = datetime.utcnow()
    today = as_of.date()

    # Fetch accounts
    accounts_stmt = select(Account).where(
        (Account.client_id == client_id) & (Account.is_active == True)
    )
    accounts_result = await db.execute(accounts_stmt)
    accounts = accounts_result.scalars().all()

    # Fetch latest statement per account
    statements_map = {}
    for account in accounts:
        stmt_query = (
            select(Statement)
            .where(Statement.account_id == account.id)
            .order_by(Statement.statement_date.desc())
            .limit(1)
        )
        stmt_result = await db.execute(stmt_query)
        statement = stmt_result.scalar()
        if statement:
            statements_map[account.id] = statement

    # Fetch FX rates for today, fall back to prior day
    fx_rates_warning = False
    fx_rates_date = today
    fx_rates_map = {}

    fx_query = (
        select(FXRate)
        .where((FXRate.client_id == client_id) & (FXRate.rate_date == today))
    )
    fx_result = await db.execute(fx_query)
    fx_today = {r.currency_from: r.rate for r in fx_result.scalars().all()}

    if len(fx_today) == 0 or any(acc.currency != "USD" and acc.currency not in fx_today for acc in accounts):
        # Try yesterday
        yesterday = today - timedelta(days=1)
        fx_query = (
            select(FXRate)
            .where((FXRate.client_id == client_id) & (FXRate.rate_date == yesterday))
        )
        fx_result = await db.execute(fx_query)
        fx_yesterday = {r.currency_from: r.rate for r in fx_result.scalars().all()}
        fx_today.update(fx_yesterday)
        if any(acc.currency != "USD" and acc.currency in fx_yesterday for acc in accounts):
            fx_rates_warning = True
            fx_rates_date = yesterday

    # Build fx rates map
    for currency in ["USD", "GBP", "EUR", "SGD"]:
        if currency == "USD":
            fx_rates_map[currency] = Decimal("1.0")
        else:
            fx_rates_map[currency] = fx_today.get(currency, Decimal("1.0"))

    # Fetch legal entities
    entities_stmt = select(LegalEntity).where(LegalEntity.client_id == client_id)
    entities_result = await db.execute(entities_stmt)
    entities = {e.id: e for e in entities_result.scalars().all()}

    # Calculate totals
    total_cash_usd = Decimal("0")
    available_cash_usd = Decimal("0")
    restricted_cash_usd = Decimal("0")
    od_limit_total_usd = Decimal("0")

    # Per-account data for confidence
    account_details = []
    active_breaches = []
    stale_feeds = []
    missing_feeds = []

    for account in accounts:
        statement = statements_map.get(account.id)
        if not statement:
            if account.refresh_frequency != "Manual":
                missing_feeds.append(account.account_name)
            continue

        closing_bal = statement.closing_balance or Decimal("0")
        available_bal = statement.available_balance or closing_bal
        fx_rate = fx_rates_map.get(account.currency, Decimal("1.0"))

        # Staleness check
        hours_stale = (as_of - statement.ingested_at).total_seconds() / 3600
        if account.refresh_frequency == "Daily":
            if hours_stale < 24:
                confidence = "High"
            elif hours_stale < 48:
                confidence = "Medium"
            else:
                confidence = "Low"
                stale_feeds.append(
                    {"account_name": account.account_name, "hours_stale": int(hours_stale)}
                )
        elif account.refresh_frequency in ["Weekly", "Monthly"]:
            if hours_stale < 48:
                confidence = "High"
            elif hours_stale < 96:
                confidence = "Medium"
            else:
                confidence = "Low"
                stale_feeds.append(
                    {"account_name": account.account_name, "hours_stale": int(hours_stale)}
                )
        else:  # Manual
            confidence = "High"

        # od_utilised flag
        od_utilised = closing_bal < 0
        od_headroom = None
        if account.od_limit and od_utilised:
            od_headroom = account.od_limit - (account.od_utilised_amount or abs(closing_bal))

        # Status calculation
        if available_bal >= account.min_threshold:
            status = "Green"
        elif available_bal >= account.min_threshold * Decimal("0.70"):
            status = "Yellow"
        else:
            status = "Red"

        # Add to totals (only if include_in_cash_position == TRUE)
        if account.include_in_cash_position:
            closing_usd = closing_bal * fx_rate
            available_usd = available_bal * fx_rate

            total_cash_usd += closing_usd
            available_cash_usd += available_usd

            if account.restricted_flag:
                restricted_cash_usd += available_usd

            if account.od_limit:
                od_limit_total_usd += account.od_limit * fx_rate

        # Check for breaches
        if available_bal < account.min_threshold:
            active_breaches.append({
                "entity_name": entities[account.entity_id].name,
                "account_name": account.account_name,
                "min_threshold": float(account.min_threshold),
                "current_balance": float(available_bal),
                "shortfall": float(account.min_threshold - available_bal),
                "currency": account.currency,
            })

        # Add account detail
        account_details.append({
            "account_id": str(account.id),
            "account_name": account.account_name,
            "bank": "JPMorgan" if account.bank_id else "Unknown",
            "currency": account.currency,
            "closing_balance": float(closing_bal),
            "available_balance": float(available_bal),
            "od_limit": float(account.od_limit) if account.od_limit else None,
            "od_utilised": od_utilised,
            "od_headroom": float(od_headroom) if od_headroom else None,
            "min_threshold": float(account.min_threshold),
            "restricted_flag": account.restricted_flag,
            "include_in_cash_position": account.include_in_cash_position,
            "refresh_frequency": account.refresh_frequency,
            "status": status,
            "confidence": confidence.value,
            "statement_date": str(statement.statement_date),
            "hours_stale": int(hours_stale),
        })

    # Calculate usable cash
    usable_cash_usd = available_cash_usd - restricted_cash_usd

    # Determine overall data confidence
    confidences = [acc.get("confidence", "High") for acc in account_details]
    if "Low" in confidences:
        overall_confidence = "Low"
    elif "Medium" in confidences:
        overall_confidence = "Medium"
    else:
        overall_confidence = "High"

    # Group by entity
    entities_output = []
    for entity_id, entity in entities.items():
        entity_accounts = [d for d in account_details if any(
            a.id == entity_id for a in accounts if a.entity_id == entity_id
        )]

        if not entity_accounts:
            continue

        entity_closing_local = Decimal("0")
        entity_available_local = Decimal("0")
        entity_restricted_local = Decimal("0")
        entity_od_limit_local = Decimal("0")

        for acc in entity_accounts:
            matching_account = next(a for a in accounts if str(a.id) == acc["account_id"])
            if matching_account.include_in_cash_position:
                entity_closing_local += Decimal(str(acc["closing_balance"]))
                entity_available_local += Decimal(str(acc["available_balance"]))
                if matching_account.restricted_flag:
                    entity_restricted_local += Decimal(str(acc["available_balance"]))
                if acc["od_limit"]:
                    entity_od_limit_local += Decimal(str(acc["od_limit"]))

        entity_usable_local = entity_available_local - entity_restricted_local
        fx_rate = fx_rates_map.get(entity.base_currency, Decimal("1.0"))
        entity_usable_usd = entity_usable_local * fx_rate

        entities_output.append({
            "entity_id": str(entity.id),
            "entity_name": entity.name,
            "base_currency": entity.base_currency,
            "closing_balance_local": float(entity_closing_local),
            "available_balance_local": float(entity_available_local),
            "restricted_balance_local": float(entity_restricted_local),
            "od_limit_local": float(entity_od_limit_local),
            "usable_cash_local": float(entity_usable_local),
            "usable_cash_usd": float(entity_usable_usd),
            "accounts": [d for d in account_details if any(
                str(a.id) == d["account_id"] for a in accounts
                if a.entity_id == entity_id
            )],
        })

    # Currency breakdown
    by_currency = []
    currencies_seen = set()
    for acc in account_details:
        if acc["currency"] not in currencies_seen:
            currencies_seen.add(acc["currency"])
            currency = acc["currency"]
            fx_rate = fx_rates_map.get(currency, Decimal("1.0"))

            # Only count accounts with include_in_cash_position == True
            currency_available_local = sum(
                Decimal(str(a["available_balance"])) for a in account_details
                if a["currency"] == currency and a["include_in_cash_position"]
            )
            currency_available_usd = currency_available_local * fx_rate

            total_available_usd = available_cash_usd if currency == "USD" else sum(
                Decimal(str(a["available_balance"])) * fx_rates_map.get(a["currency"], Decimal("1.0"))
                for a in account_details if a["include_in_cash_position"]
            )

            share_pct = 0.0
            if total_available_usd > 0:
                share_pct = float((currency_available_usd / total_available_usd) * 100)

            by_currency.append({
                "currency": currency,
                "available_balance_local": float(currency_available_local),
                "available_balance_usd": float(currency_available_usd),
                "share_pct": share_pct,
            })

    # Build output
    output = {
        "run_id": run_id,
        "job_id": state["job_id"],
        "client_id": state["client_id"],
        "as_of": as_of.isoformat(),
        "fx_rates_date": str(fx_rates_date),
        "fx_rates_warning": fx_rates_warning,
        "total_cash_usd": float(total_cash_usd),
        "available_cash_usd": float(available_cash_usd),
        "restricted_cash_usd": float(restricted_cash_usd),
        "usable_cash_usd": float(usable_cash_usd),
        "od_limit_total_usd": float(od_limit_total_usd),
        "data_confidence": overall_confidence.value,
        "stale_feeds": stale_feeds,
        "missing_feeds": missing_feeds,
        "entities": entities_output,
        "by_currency": by_currency,
        "active_breaches": active_breaches,
    }

    # Write to MongoDB
    collection = mongo_db["agent_runs"]
    result = await collection.insert_one(output)
    output["_id"] = str(result.inserted_id)

    return output
