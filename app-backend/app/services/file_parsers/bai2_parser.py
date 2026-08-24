import logging
from datetime import date, datetime
from typing import List, Optional

from core_cash_shared import BankStatementRow

logger = logging.getLogger(__name__)


class BAI2Parser:
    def parse(self, content_bytes: bytes, entity_id: str) -> List[BankStatementRow]:
        """
        Parse BAI2 formatted bank file.

        BAI2 structure (line-by-line, comma-delimited):
          01 = File Header
          02 = Group Header
          03 = Account Identifier
          16 = Transaction Detail
          49 = Account Trailer
          98 = Group Trailer
          99 = File Trailer
        """
        rows = []

        # Try UTF-8 first, fallback to latin-1
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1")

        lines = text.strip().split("\n")

        # Verify header
        if not lines or not lines[0].startswith("01,"):
            raise ValueError("BAI2 header missing")

        # Merge continuation records (88,)
        merged_lines = self._merge_continuation_records(lines)

        current_account_number = None
        current_currency = None

        for line_idx, line in enumerate(merged_lines):
            line = line.strip()
            if not line:
                continue

            fields = line.split(",")
            if not fields:
                continue

            record_type = fields[0]

            # Account identifier record
            if record_type == "03":
                if len(fields) > 3:
                    current_account_number = fields[3]
                if len(fields) > 4:
                    current_currency = fields[4]

            # Transaction detail record
            elif record_type == "16":
                try:
                    row = self._parse_transaction(
                        fields, entity_id, current_account_number, current_currency
                    )
                    if row:
                        rows.append(row)
                except Exception as e:
                    logger.warning(f"Failed to parse BAI2 transaction at line {line_idx}: {e}")
                    continue

        return rows

    def _merge_continuation_records(self, lines: List[str]) -> List[str]:
        """Merge continuation records (88,) with previous line."""
        merged = []
        for line in lines:
            line = line.rstrip("\r\n")
            if line.startswith("88,"):
                # Append to previous line
                if merged:
                    merged[-1] += line[2:]  # Skip "88,"
            else:
                merged.append(line)
        return merged

    def _parse_transaction(
        self,
        fields: List[str],
        entity_id: str,
        account_number: Optional[str],
        currency: Optional[str],
    ) -> Optional[BankStatementRow]:
        """Parse a 16 record (transaction detail)."""
        if len(fields) < 5:
            return None

        # Transaction date: field[1], format YYMMDD
        if len(fields) > 1:
            date_str = fields[1]
            transaction_date = self._parse_bai2_date(date_str)
            if not transaction_date:
                return None
        else:
            return None

        # Type code: field[2]
        type_code = fields[2] if len(fields) > 2 else None

        # Amount: field[3], in cents
        if len(fields) > 3:
            try:
                amount_cents = int(fields[3])
                amount = amount_cents / 100.0
            except (ValueError, TypeError):
                return None
        else:
            return None

        # Determine debit/credit based on type code
        debit_amount = None
        credit_amount = None
        if type_code:
            try:
                type_code_num = int(type_code)
                if 100 <= type_code_num <= 199:
                    credit_amount = amount
                elif 400 <= type_code_num <= 499:
                    debit_amount = amount
                else:
                    # Unknown type code - store in raw_type_code, amounts None
                    logger.warning(f"Unknown BAI2 type code: {type_code}")
            except (ValueError, TypeError):
                pass

        # Description: join all text fields after field[4]
        description_parts = fields[4:] if len(fields) > 4 else []
        description = " ".join(p for p in description_parts if p).strip()

        return BankStatementRow(
            entity_id=entity_id,
            account_id=None,  # Will be matched later
            account_number_raw=account_number or "",
            transaction_date=transaction_date,
            value_date=None,
            description=description,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            currency=currency or "USD",
            balance_after=None,
            source_format="BAI2",
            raw_type_code=type_code,
        )

    def _parse_bai2_date(self, date_str: str) -> Optional[date]:
        """Parse YYMMDD to date. Century: 00–30 → 2000s, 31–99 → 1900s."""
        if not date_str or len(date_str) != 6:
            return None
        try:
            yy = int(date_str[:2])
            mm = int(date_str[2:4])
            dd = int(date_str[4:6])

            # Century rule
            if yy <= 30:
                yyyy = 2000 + yy
            else:
                yyyy = 1900 + yy

            return date(yyyy, mm, dd)
        except (ValueError, TypeError):
            return None
