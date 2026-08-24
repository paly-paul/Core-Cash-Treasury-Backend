import logging
import re
from datetime import date
from typing import Dict, List, Optional

from core_cash_shared import BankStatementRow

logger = logging.getLogger(__name__)


class MT940Parser:
    def parse(self, content_bytes: bytes, entity_id: str) -> List[BankStatementRow]:
        """Parse MT940 (SWIFT Customer Statement Message) formatted bank file."""
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1")

        rows = []

        # Split into statements by :20: tag (multiple statements may exist)
        statements = text.split(":20:")
        statements = [":20:" + s for s in statements[1:]]  # Skip empty first element

        for stmt_block in statements:
            rows.extend(self._parse_statement(stmt_block, entity_id))

        return rows

    def _parse_statement(self, stmt_text: str, entity_id: str) -> List[BankStatementRow]:
        """Parse a single MT940 statement block."""
        rows = []

        # Extract all tags
        tags = self._extract_tags(stmt_text)

        # Get account number from :25: tag
        account_number = tags.get("25", "")
        if not account_number:
            raise ValueError("MT940: account identifier missing")

        # Strip currency suffix if present (everything after /)
        if "/" in account_number:
            account_number = account_number.split("/")[0]

        # Get currency from :60F: (opening balance) if available
        opening_balance_line = tags.get("60F", "")
        currency = self._extract_currency_from_balance_line(opening_balance_line) or "USD"

        # Collect closing balance from :62F: for last transaction
        closing_balance_line = tags.get("62F", "")
        closing_balance = self._extract_balance_from_balance_line(closing_balance_line)

        # Parse all :61: (statement line) tags
        statement_lines = []
        for line_text in tags.get("61_list", []):
            txn = self._parse_statement_line(line_text, entity_id, account_number, currency)
            if txn:
                statement_lines.append(txn)

        # Apply closing balance to the last transaction only
        if statement_lines and closing_balance is not None:
            statement_lines[-1].balance_after = closing_balance

        rows.extend(statement_lines)
        return rows

    def _extract_tags(self, text: str) -> Dict[str, any]:
        """Extract MT940 tags from text."""
        tags = {}
        tags["61_list"] = []

        # Handle multi-line :86: (information to account owner)
        # Replace multi-line :86: with single line before parsing
        text = self._merge_continuation_lines(text)

        # Find all :NN: and :NNC: tags
        pattern = r":(\d{2}[A-Z]?):"
        matches = list(re.finditer(pattern, text))

        for i, match in enumerate(matches):
            tag_code = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()

            if tag_code == "61":
                tags["61_list"].append(content)
            elif tag_code == "86":
                # Store :86: with its preceding :61:
                if tags["61_list"]:
                    tags["86_list"] = getattr(tags, "86_list", [])
                    tags.setdefault("86_list", []).append(content)
            else:
                tags[tag_code] = content

        return tags

    def _merge_continuation_lines(self, text: str) -> str:
        """Merge multi-line :86: tags into single lines."""
        lines = text.split("\n")
        merged = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # If it starts with :86:, collect continuation lines
            if ":86:" in line:
                merged.append(line)
                i += 1
                # Continuation lines don't start with :
                while i < len(lines) and not re.match(r"^:", lines[i]):
                    merged[-1] += " " + lines[i].strip()
                    i += 1
            else:
                merged.append(line)
                i += 1
        return "\n".join(merged)

    def _parse_statement_line(
        self, line_text: str, entity_id: str, account_number: str, currency: str
    ) -> Optional[BankStatementRow]:
        """Parse a :61: tag (statement line)."""
        line_text = line_text.strip()
        if len(line_text) < 6:
            return None

        # Value date: positions 0–5 (YYMMDD)
        value_date_str = line_text[0:6]
        transaction_date = self._parse_mt940_date(value_date_str)
        if not transaction_date:
            return None

        # Entry date (optional): positions 6–9 (MMDD) — skip if 4 chars
        pos = 6
        if len(line_text) > pos + 4 and line_text[pos : pos + 4].isdigit():
            pos += 4

        # Credit/Debit indicator: C or D (or RC/RD)
        if pos >= len(line_text):
            return None

        c_or_d = ""
        if line_text[pos : pos + 2] in ["RC", "RD"]:
            c_or_d = line_text[pos : pos + 2]
            pos += 2
        else:
            c_or_d = line_text[pos]
            pos += 1

        # Amount: remaining text up to transaction code
        # Amount contains comma as decimal separator
        # Transaction code is typically last 4 alphanumeric chars
        remaining = line_text[pos:]

        # Find where amount ends and transaction code begins
        # Amount is: digits, comma for decimal, more digits
        # Transaction code is typically 4 chars of digits/letters
        amount_match = re.match(r"(\d+,\d+)", remaining)
        if not amount_match:
            logger.warning(f"MT940: invalid amount format in {line_text}")
            return None

        amount_str = amount_match.group(1)
        amount = float(amount_str.replace(",", "."))

        # Transaction code (raw_type_code)
        txn_code_pos = len(amount_str)
        raw_type_code = remaining[txn_code_pos:].strip() if txn_code_pos < len(remaining) else None

        # Determine debit/credit
        debit_amount = None
        credit_amount = None

        if c_or_d in ["C", "RC"]:
            credit_amount = amount
        elif c_or_d in ["D", "RD"]:
            debit_amount = amount

        return BankStatementRow(
            entity_id=entity_id,
            account_id=None,  # Will be matched later
            account_number_raw=account_number,
            transaction_date=transaction_date,
            value_date=transaction_date,  # MT940 doesn't distinguish separately
            description="",  # Will be populated from :86: in post-processing
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            currency=currency,
            balance_after=None,
            source_format="MT940",
            raw_type_code=raw_type_code,
        )

    def _parse_mt940_date(self, date_str: str) -> Optional[date]:
        """Parse YYMMDD to date. Century: 00–30 → 20xx, 31–99 → 19xx."""
        if not date_str or len(date_str) != 6:
            return None
        try:
            yy = int(date_str[0:2])
            mm = int(date_str[2:4])
            dd = int(date_str[4:6])

            if yy <= 30:
                yyyy = 2000 + yy
            else:
                yyyy = 1900 + yy

            return date(yyyy, mm, dd)
        except (ValueError, TypeError):
            return None

    def _extract_currency_from_balance_line(self, line: str) -> Optional[str]:
        """Extract currency code from :60F: or :62F: line."""
        if not line or len(line) < 6:
            return None
        # Format: C/D + YYMMDD + currency (3 chars) + amount
        # Positions 7-9 are currency
        try:
            return line[6:9]
        except Exception:
            return None

    def _extract_balance_from_balance_line(self, line: str) -> Optional[float]:
        """Extract balance amount from :60F: or :62F: line."""
        if not line or len(line) < 10:
            return None
        # Format: C/D + YYMMDD + currency (3 chars) + amount
        # Amount starts at position 9+
        try:
            amount_str = line[9:].strip()
            return float(amount_str.replace(",", "."))
        except (ValueError, TypeError):
            return None
