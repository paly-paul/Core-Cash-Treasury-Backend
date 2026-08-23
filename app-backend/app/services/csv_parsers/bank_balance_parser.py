from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.account import Account
from app.models.statement import Statement
from app.services.csv_parsers.base_parser import BaseParser, ValidationError


class BankBalanceParser(BaseParser):
    REQUIRED_COLUMNS = {
        "account_name": ["Account Name", "Account", "AccountName", "Account Title", "Bank Account"],
        "statement_date": ["Date", "Statement Date", "Balance Date", "As Of Date", "Value Date"],
        "closing_balance": ["Closing Balance", "Balance", "Closing", "End Balance", "Ledger Balance", "Book Balance"],
        "available_balance": ["Available Balance", "Available", "Cleared Balance", "Usable Balance"],
        "currency": ["Currency", "CCY", "Ccy"],
    }

    @staticmethod
    async def parse_and_store(
        content: bytes,
        client_id: UUID,
        filename: str,
        db: AsyncSession,
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> Dict:
        BankBalanceParser.validate_file_format(filename)
        BankBalanceParser.validate_file_size(content)

        fieldnames, rows = BankBalanceParser.read_csv(content)
        resolved_cols, _ = BankBalanceParser.resolve_columns(
            fieldnames, BankBalanceParser.REQUIRED_COLUMNS, column_mapping
        )

        rows_received = len(rows)
        rows_valid = 0
        rows_failed = 0
        flagged_rows = []
        negative_balances_detected = 0
        negative_balance_accounts = []
        statements_to_insert = []

        result = await db.execute(
            select(Account).where(Account.client_id == client_id)
        )
        accounts = result.scalars().all()
        account_map = {acc.account_name.lower(): acc for acc in accounts}

        for row_idx, row in enumerate(rows, start=2):
            try:
                account_name = row.get(resolved_cols["account_name"], "").strip()
                statement_date_str = row.get(resolved_cols["statement_date"], "").strip()
                closing_balance_str = row.get(resolved_cols["closing_balance"], "").strip()
                available_balance_str = row.get(resolved_cols["available_balance"], "").strip()
                currency = row.get(resolved_cols["currency"], "").strip().upper()

                if not account_name:
                    rows_failed += 1
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": "Account name is empty",
                        "action": "Skipped row"
                    })
                    continue

                parsed_date = BankBalanceParser.parse_date(statement_date_str)
                if not parsed_date:
                    rows_failed += 1
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": f"Invalid date format: {statement_date_str}",
                        "action": "Skipped row"
                    })
                    continue

                closing_balance = BankBalanceParser.parse_decimal(closing_balance_str)
                if closing_balance is None:
                    rows_failed += 1
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": f"Invalid closing balance: {closing_balance_str}",
                        "action": "Skipped row"
                    })
                    continue

                available_balance = None
                if available_balance_str:
                    available_balance = BankBalanceParser.parse_decimal(available_balance_str)
                    if available_balance is None:
                        rows_failed += 1
                        flagged_rows.append({
                            "row": row_idx,
                            "issue": f"Invalid available balance: {available_balance_str}",
                            "action": "Skipped row"
                        })
                        continue

                if currency not in ["USD", "GBP", "EUR"]:
                    rows_failed += 1
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": f"Unsupported currency: {currency}",
                        "action": "Skipped row"
                    })
                    continue

                account_id = None
                confidence = "Low"
                if account_name.lower() in account_map:
                    account_id = account_map[account_name.lower()].id
                    hours_stale = BankBalanceParser.calculate_hours_stale(parsed_date)
                    if hours_stale <= 24:
                        confidence = "High"
                    elif hours_stale <= 48:
                        confidence = "Medium"
                else:
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": f"Unmapped account — Account Name '{account_name}' not in Account Master",
                        "action": "Included with Low confidence; map in Account Master to resolve"
                    })

                if closing_balance < 0:
                    negative_balances_detected += 1
                    negative_balance_accounts.append(f"{account_name} — treated as OD utilisation")

                statements_to_insert.append({
                    "account_id": account_id,
                    "statement_date": parsed_date.date(),
                    "closing_balance": closing_balance,
                    "available_balance": available_balance or closing_balance,
                    "currency": currency,
                    "source": "csv",
                    "confidence": confidence,
                    "source_file_id": None,
                })
                rows_valid += 1

            except Exception as e:
                rows_failed += 1
                flagged_rows.append({
                    "row": row_idx,
                    "issue": str(e),
                    "action": "Skipped row"
                })

        return {
            "rows_received": rows_received,
            "rows_valid": rows_valid,
            "rows_failed": rows_failed,
            "rows_flagged": len(flagged_rows),
            "flagged_rows": flagged_rows,
            "statements": statements_to_insert,
            "negative_balances_detected": negative_balances_detected,
            "negative_balance_accounts": negative_balance_accounts,
        }

    @staticmethod
    def calculate_hours_stale(statement_date: datetime) -> int:
        statement_midnight = datetime.combine(statement_date.date(), datetime.min.time())
        now = datetime.utcnow()
        delta = now - statement_midnight
        return int(delta.total_seconds() / 3600)
