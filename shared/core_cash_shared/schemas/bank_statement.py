from datetime import date
from typing import Optional

from pydantic import BaseModel


class BankStatementRow(BaseModel):
    entity_id: str
    account_id: Optional[str]
    account_number_raw: str
    transaction_date: date
    value_date: Optional[date] = None
    description: str
    debit_amount: Optional[float] = None
    credit_amount: Optional[float] = None
    currency: str
    balance_after: Optional[float] = None
    source_format: str  # "BAI2" | "CAMT053" | "MT940" | "CSV"
    raw_type_code: Optional[str] = None
