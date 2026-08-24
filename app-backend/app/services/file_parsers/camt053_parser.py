import logging
import re
import xml.etree.ElementTree as ET
from datetime import date
from typing import List, Optional

from core_cash_shared import BankStatementRow

logger = logging.getLogger(__name__)


class Camt053Parser:
    def parse(self, content_bytes: bytes, entity_id: str) -> List[BankStatementRow]:
        """Parse camt.053 (ISO 20022 XML) formatted bank file."""
        try:
            root = ET.fromstring(content_bytes)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")

        # Extract namespace
        ns = self._extract_namespace(root.tag)
        ns_prefix = f"{{{ns}}}" if ns else ""

        rows = []

        # Account IBAN/number
        account_id_elem = root.find(f".//{ns_prefix}Stmt/{ns_prefix}Acct/{ns_prefix}Id/{ns_prefix}IBAN")
        if account_id_elem is None:
            account_id_elem = root.find(
                f".//{ns_prefix}Stmt/{ns_prefix}Acct/{ns_prefix}Id/{ns_prefix}Othr/{ns_prefix}Id"
            )
        account_number = account_id_elem.text if account_id_elem is not None else ""

        # Currency
        ccy_elem = root.find(f".//{ns_prefix}Stmt/{ns_prefix}Acct/{ns_prefix}Ccy")
        currency = ccy_elem.text if ccy_elem is not None else "USD"

        # Transactions
        entries = root.findall(f".//{ns_prefix}Stmt/{ns_prefix}Ntry")

        for entry in entries:
            try:
                row = self._parse_entry(entry, entity_id, account_number, currency, ns_prefix)
                if row:
                    rows.append(row)
            except Exception as e:
                logger.warning(f"Failed to parse camt.053 entry: {e}")
                continue

        if not rows:
            raise ValueError("camt.053: no valid transactions parsed")

        return rows

    def _extract_namespace(self, tag: str) -> str:
        """Extract namespace from XML tag."""
        match = re.match(r"\{(.+?)\}", tag)
        return match.group(1) if match else ""

    def _parse_entry(
        self, entry: ET.Element, entity_id: str, account_number: str, currency: str, ns_prefix: str
    ) -> Optional[BankStatementRow]:
        """Parse a Ntry (transaction) element."""
        # Booking date (required)
        booking_date_elem = entry.find(f".//{ns_prefix}BookgDt/{ns_prefix}Dt")
        if booking_date_elem is None:
            logger.warning("Missing BookgDt in camt.053 entry")
            return None

        transaction_date = self._parse_date(booking_date_elem.text)
        if not transaction_date:
            logger.warning(f"Invalid BookgDt format: {booking_date_elem.text}")
            return None

        # Value date (optional)
        value_date_elem = entry.find(f".//{ns_prefix}ValDt/{ns_prefix}Dt")
        value_date = self._parse_date(value_date_elem.text) if value_date_elem is not None else None

        # Amount
        amount_elem = entry.find(f".//{ns_prefix}Amt")
        if amount_elem is None:
            logger.warning("Missing Amt in camt.053 entry")
            return None

        try:
            amount = float(amount_elem.text)
        except (ValueError, TypeError):
            logger.warning(f"Invalid amount format: {amount_elem.text}")
            return None

        # Credit/Debit indicator
        cd_ind_elem = entry.find(f".//{ns_prefix}CdtDbtInd")
        if cd_ind_elem is None:
            logger.warning("Missing CdtDbtInd in camt.053 entry")
            return None

        cd_ind = cd_ind_elem.text.strip().upper()
        debit_amount = None
        credit_amount = None

        if cd_ind == "CRDT":
            credit_amount = amount
        elif cd_ind == "DBIT":
            debit_amount = amount
        else:
            logger.warning(f"Unknown CdtDbtInd: {cd_ind}")
            return None

        # Description (Ustrd)
        description_parts = []
        ustrd_elems = entry.findall(f".//{ns_prefix}RmtInf/{ns_prefix}Ustrd")
        description_parts.extend([e.text for e in ustrd_elems if e.text])

        # Fallback: AddtlNtryInf
        if not description_parts:
            addtl_elem = entry.find(f".//{ns_prefix}AddtlNtryInf")
            if addtl_elem is not None and addtl_elem.text:
                description_parts.append(addtl_elem.text)

        description = " | ".join(description_parts) if description_parts else ""

        # Type code
        type_code_elem = entry.find(f".//{ns_prefix}BkTxCd/{ns_prefix}Prtry/{ns_prefix}Cd")
        type_code = type_code_elem.text if type_code_elem is not None else None

        return BankStatementRow(
            entity_id=entity_id,
            account_id=None,  # Will be matched later
            account_number_raw=account_number,
            transaction_date=transaction_date,
            value_date=value_date,
            description=description,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            currency=currency,
            balance_after=None,
            source_format="CAMT053",
            raw_type_code=type_code,
        )

    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse ISO 8601 date (YYYY-MM-DD)."""
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str.strip())
        except (ValueError, TypeError):
            return None
