from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.legal_entity import LegalEntity
from app.services.csv_parsers.base_parser import BaseParser, ValidationError


class APParser(BaseParser):
    REQUIRED_COLUMNS = {
        "entity": ["Entity", "Entity Name", "Business Unit"],
        "vendor_name": ["Vendor Name", "Vendor", "Supplier"],
        "invoice_number": ["Invoice Number", "Invoice #", "INV #"],
        "invoice_date": ["Invoice Date", "Date"],
        "due_date": ["Due Date", "Payment Due Date"],
        "currency": ["Currency", "CCY", "Ccy"],
        "amount_local": ["Amount", "Amount (Local)", "Invoice Amount"],
        "category": ["Category", "Category Type", "Classification"],
    }

    @staticmethod
    async def parse_and_store(
        content: bytes,
        client_id: UUID,
        filename: str,
        db: AsyncSession,
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> Dict:
        APParser.validate_file_format(filename)
        APParser.validate_file_size(content)

        fieldnames, rows = APParser.read_csv(content)
        resolved_cols, _ = APParser.resolve_columns(
            fieldnames, APParser.REQUIRED_COLUMNS, column_mapping
        )

        rows_received = len(rows)
        rows_valid = 0
        rows_failed = 0
        flagged_rows = []
        ap_rows_to_insert = []

        result = await db.execute(
            select(LegalEntity).where(LegalEntity.client_id == client_id)
        )
        entities = result.scalars().all()
        entity_map = {ent.name.lower(): ent for ent in entities}

        for row_idx, row in enumerate(rows, start=2):
            try:
                entity_name = row.get(resolved_cols["entity"], "").strip()
                vendor_name = row.get(resolved_cols["vendor_name"], "").strip()
                invoice_number = row.get(resolved_cols["invoice_number"], "").strip() if "invoice_number" in resolved_cols else None
                invoice_date_str = row.get(resolved_cols["invoice_date"], "").strip() if "invoice_date" in resolved_cols else None
                due_date_str = row.get(resolved_cols["due_date"], "").strip()
                currency = row.get(resolved_cols["currency"], "").strip().upper()
                amount_str = row.get(resolved_cols["amount_local"], "").strip()
                category = row.get(resolved_cols["category"], "").strip() if "category" in resolved_cols else None

                if not vendor_name:
                    rows_failed += 1
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": "Vendor name is empty",
                        "action": "Skipped row"
                    })
                    continue

                if not due_date_str:
                    rows_failed += 1
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": "Due date is required",
                        "action": "Skipped row"
                    })
                    continue

                amount = APParser.parse_decimal(amount_str)
                if amount is None or amount <= 0:
                    rows_failed += 1
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": f"Invalid amount: {amount_str}",
                        "action": "Skipped row"
                    })
                    continue

                due_date = None
                if due_date_str:
                    due_date = APParser.parse_date(due_date_str)
                    if not due_date:
                        rows_failed += 1
                        flagged_rows.append({
                            "row": row_idx,
                            "issue": f"Invalid due date format: {due_date_str}",
                            "action": "Skipped row"
                        })
                        continue

                invoice_date = None
                if invoice_date_str:
                    invoice_date = APParser.parse_date(invoice_date_str)
                    if not invoice_date:
                        rows_failed += 1
                        flagged_rows.append({
                            "row": row_idx,
                            "issue": f"Invalid invoice date format: {invoice_date_str}",
                            "action": "Skipped row"
                        })
                        continue

                if invoice_date and due_date and due_date < invoice_date:
                    rows_failed += 1
                    flagged_rows.append({
                        "row": row_idx,
                        "issue": "due_date cannot be before invoice_date",
                        "action": "Skipped row"
                    })
                    continue

                entity_id = None
                if entity_name.lower() in entity_map:
                    entity_id = entity_map[entity_name.lower()].id

                ap_rows_to_insert.append({
                    "client_id": client_id,
                    "entity_id": entity_id,
                    "vendor_name": vendor_name,
                    "invoice_number": invoice_number,
                    "invoice_date": invoice_date.date() if invoice_date else None,
                    "due_date": due_date.date() if due_date else None,
                    "currency": currency,
                    "amount_local": amount,
                    "category": category,
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
            "ap_rows": ap_rows_to_insert,
        }
