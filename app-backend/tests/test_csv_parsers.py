import csv
import io
import json
from decimal import Decimal
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source_file import SourceFile
from app.models.ar_data import ARData
from app.models.ap_data import APData
from app.models.statement import Statement
from app.services.csv_parsers.bank_balance_parser import BankBalanceParser
from app.services.csv_parsers.ar_parser import ARParser
from app.services.csv_parsers.ap_parser import APParser
from app.services.csv_parsers.base_parser import ValidationError


@pytest.fixture
def client_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


def create_csv_content(headers: list, rows: list) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode('utf-8')


# Bank Balance Tests

@pytest.mark.asyncio
async def test_bank_balance_happy_path(db: AsyncSession, client_id: str):
    """Test: 6-row CSV, all valid, all accounts matched."""
    headers = ["Account Name", "Date", "Closing Balance", "Available Balance", "Currency"]
    rows = [
        {"Account Name": "JPM USD Main", "Date": "2026-08-22", "Closing Balance": "1000000", "Available Balance": "1000000", "Currency": "USD"},
        {"Account Name": "JPM USD Main", "Date": "2026-08-21", "Closing Balance": "950000", "Available Balance": "950000", "Currency": "USD"},
        {"Account Name": "Barclays GBP Ops", "Date": "2026-08-22", "Closing Balance": "500000", "Available Balance": "500000", "Currency": "GBP"},
        {"Account Name": "Barclays GBP Ops", "Date": "2026-08-21", "Closing Balance": "480000", "Available Balance": "480000", "Currency": "GBP"},
        {"Account Name": "BofA EUR Reserve", "Date": "2026-08-22", "Closing Balance": "300000", "Available Balance": "300000", "Currency": "EUR"},
        {"Account Name": "EUR OD Test", "Date": "2026-08-22", "Closing Balance": "-50000", "Available Balance": "0", "Currency": "EUR"},
    ]
    content = create_csv_content(headers, rows)
    result = await BankBalanceParser.parse_and_store(content, client_id, "test.csv", db)

    assert result["rows_valid"] == 6
    assert result["rows_failed"] == 0
    assert result["rows_flagged"] == 0


@pytest.mark.asyncio
async def test_bank_balance_unmatched_account(db: AsyncSession, client_id: str):
    """Test: 1 row with account name not in account master."""
    headers = ["Account Name", "Date", "Closing Balance", "Available Balance", "Currency"]
    rows = [
        {"Account Name": "Unknown Account", "Date": "2026-08-22", "Closing Balance": "1000000", "Available Balance": "1000000", "Currency": "USD"},
        {"Account Name": "JPM USD Main", "Date": "2026-08-22", "Closing Balance": "500000", "Available Balance": "500000", "Currency": "USD"},
        {"Account Name": "JPM USD Main", "Date": "2026-08-21", "Closing Balance": "480000", "Available Balance": "480000", "Currency": "USD"},
        {"Account Name": "Barclays GBP Ops", "Date": "2026-08-22", "Closing Balance": "300000", "Available Balance": "300000", "Currency": "GBP"},
        {"Account Name": "BofA EUR Reserve", "Date": "2026-08-22", "Closing Balance": "200000", "Available Balance": "200000", "Currency": "EUR"},
        {"Account Name": "EUR OD Test", "Date": "2026-08-22", "Closing Balance": "-25000", "Available Balance": "0", "Currency": "EUR"},
    ]
    content = create_csv_content(headers, rows)
    result = await BankBalanceParser.parse_and_store(content, client_id, "test.csv", db)

    assert result["rows_valid"] == 5
    assert result["rows_failed"] == 0
    assert result["rows_flagged"] == 1
    assert len(result["flagged_rows"]) == 1
    assert "not in Account Master" in result["flagged_rows"][0]["issue"]


@pytest.mark.asyncio
async def test_bank_balance_negative_balance(db: AsyncSession, client_id: str):
    """Test: 1 row with negative closing_balance."""
    headers = ["Account Name", "Date", "Closing Balance", "Available Balance", "Currency"]
    rows = [
        {"Account Name": "EUR OD Test", "Date": "2026-08-22", "Closing Balance": "-50000", "Available Balance": "0", "Currency": "EUR"},
    ]
    content = create_csv_content(headers, rows)
    result = await BankBalanceParser.parse_and_store(content, client_id, "test.csv", db)

    assert result["negative_balances_detected"] == 1
    assert len(result["negative_balance_accounts"]) == 1
    assert "OD utilisation" in result["negative_balance_accounts"][0]


@pytest.mark.asyncio
async def test_bank_balance_wrong_format():
    """Test: .xlsx file."""
    with pytest.raises(ValidationError) as exc_info:
        BankBalanceParser.validate_file_format("test.xlsx")
    assert exc_info.value.code == "VALIDATION_UNSUPPORTED_FORMAT"


@pytest.mark.asyncio
async def test_bank_balance_too_large():
    """Test: File > 10 MB."""
    content = b"x" * (11 * 1024 * 1024)
    with pytest.raises(ValidationError) as exc_info:
        BankBalanceParser.validate_file_size(content)
    assert exc_info.value.code == "VALIDATION_FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_bank_balance_all_rows_fail(db: AsyncSession, client_id: str):
    """Test: All rows have unparseable dates."""
    headers = ["Account Name", "Date", "Closing Balance", "Available Balance", "Currency"]
    rows = [
        {"Account Name": "JPM USD Main", "Date": "invalid_date", "Closing Balance": "1000000", "Available Balance": "1000000", "Currency": "USD"},
        {"Account Name": "Barclays GBP Ops", "Date": "another_bad_date", "Closing Balance": "500000", "Available Balance": "500000", "Currency": "GBP"},
        {"Account Name": "BofA EUR Reserve", "Date": "not_a_date", "Closing Balance": "300000", "Available Balance": "300000", "Currency": "EUR"},
    ]
    content = create_csv_content(headers, rows)
    result = await BankBalanceParser.parse_and_store(content, client_id, "test.csv", db)

    assert result["rows_valid"] == 0
    assert result["rows_failed"] == 3


# AR Tests

@pytest.mark.asyncio
async def test_ar_happy_path(db: AsyncSession, client_id: str):
    """Test: 5 rows, all valid."""
    headers = ["Entity", "Counterparty Name", "Invoice Number", "Invoice Date", "Due Date", "Currency", "Amount", "Status"]
    rows = [
        {"Entity": "US HQ", "Counterparty Name": "Customer A", "Invoice Number": "INV-001", "Invoice Date": "2026-08-01", "Due Date": "2026-08-22", "Currency": "USD", "Amount": "100000", "Status": "Open"},
        {"Entity": "US HQ", "Counterparty Name": "Customer B", "Invoice Number": "INV-002", "Invoice Date": "2026-08-02", "Due Date": "2026-08-21", "Currency": "USD", "Amount": "150000", "Status": "Open"},
        {"Entity": "UK Operations", "Counterparty Name": "GlobalTech Ltd", "Invoice Number": "INV-003", "Invoice Date": "2026-07-15", "Due Date": "2026-08-10", "Currency": "GBP", "Amount": "50000", "Status": "Overdue"},
        {"Entity": "EU Entity", "Counterparty Name": "EU Corp", "Invoice Number": "INV-004", "Invoice Date": "2026-08-05", "Due Date": "2026-08-25", "Currency": "EUR", "Amount": "75000", "Status": "Open"},
        {"Entity": "APAC Hub", "Counterparty Name": "Asia Partner", "Invoice Number": "INV-005", "Invoice Date": "2026-08-10", "Due Date": "2026-08-27", "Currency": "USD", "Amount": "200000", "Status": "Open"},
    ]
    content = create_csv_content(headers, rows)
    result = await ARParser.parse_and_store(content, client_id, "test.csv", db)

    assert result["rows_valid"] == 5
    assert result["rows_failed"] == 0
    assert result["rows_flagged"] == 0


@pytest.mark.asyncio
async def test_ar_bad_row_due_before_invoice(db: AsyncSession, client_id: str):
    """Test: 1 bad row (due_date before invoice_date)."""
    headers = ["Entity", "Counterparty Name", "Invoice Number", "Invoice Date", "Due Date", "Currency", "Amount", "Status"]
    rows = [
        {"Entity": "US HQ", "Counterparty Name": "Customer A", "Invoice Number": "INV-001", "Invoice Date": "2026-08-25", "Due Date": "2026-08-20", "Currency": "USD", "Amount": "100000", "Status": "Open"},
        {"Entity": "US HQ", "Counterparty Name": "Customer B", "Invoice Number": "INV-002", "Invoice Date": "2026-08-02", "Due Date": "2026-08-21", "Currency": "USD", "Amount": "150000", "Status": "Open"},
        {"Entity": "UK Operations", "Counterparty Name": "GlobalTech Ltd", "Invoice Number": "INV-003", "Invoice Date": "2026-07-15", "Due Date": "2026-08-10", "Currency": "GBP", "Amount": "50000", "Status": "Overdue"},
        {"Entity": "EU Entity", "Counterparty Name": "EU Corp", "Invoice Number": "INV-004", "Invoice Date": "2026-08-05", "Due Date": "2026-08-25", "Currency": "EUR", "Amount": "75000", "Status": "Open"},
    ]
    content = create_csv_content(headers, rows)
    result = await ARParser.parse_and_store(content, client_id, "test.csv", db)

    assert result["rows_valid"] == 3
    assert result["rows_failed"] == 1
    assert result["rows_flagged"] == 1
    assert "due_date cannot be before invoice_date" in result["flagged_rows"][0]["issue"]


# AP Tests

@pytest.mark.asyncio
async def test_ap_happy_path(db: AsyncSession, client_id: str):
    """Test: 5 rows, all valid."""
    headers = ["Entity", "Vendor Name", "Invoice Number", "Invoice Date", "Due Date", "Currency", "Amount", "Category"]
    rows = [
        {"Entity": "US HQ", "Vendor Name": "Supplier A", "Invoice Number": "AP-001", "Invoice Date": "2026-08-01", "Due Date": "2026-08-22", "Currency": "USD", "Amount": "100000", "Category": "AP"},
        {"Entity": "US HQ", "Vendor Name": "Supplier B", "Invoice Number": "AP-002", "Invoice Date": "2026-08-02", "Due Date": "2026-08-21", "Currency": "USD", "Amount": "150000", "Category": "AP"},
        {"Entity": "UK Operations", "Vendor Name": "UK Supplier", "Invoice Number": "AP-003", "Invoice Date": "2026-07-15", "Due Date": "2026-08-10", "Currency": "GBP", "Amount": "50000", "Category": "AP"},
        {"Entity": "EU Entity", "Vendor Name": "EU Vendor", "Invoice Number": "AP-004", "Invoice Date": "2026-08-05", "Due Date": "2026-08-25", "Currency": "EUR", "Amount": "75000", "Category": "Capex"},
        {"Entity": "APAC Hub", "Vendor Name": "Asia Supplier", "Invoice Number": "AP-005", "Invoice Date": "2026-08-10", "Due Date": "2026-08-27", "Currency": "USD", "Amount": "200000", "Category": "Tax"},
    ]
    content = create_csv_content(headers, rows)
    result = await APParser.parse_and_store(content, client_id, "test.csv", db)

    assert result["rows_valid"] == 5
    assert result["rows_failed"] == 0
    assert result["rows_flagged"] == 0


# Column Mapping Test

@pytest.mark.asyncio
async def test_bank_balance_column_mapping(db: AsyncSession, client_id: str):
    """Test: Non-standard headers + column_mapping override."""
    headers = ["Acct", "Stmnt Date", "End Bal", "Clear Bal", "Ccy"]
    rows = [
        {"Acct": "JPM USD Main", "Stmnt Date": "2026-08-22", "End Bal": "1000000", "Clear Bal": "1000000", "Ccy": "USD"},
    ]
    content = create_csv_content(headers, rows)

    column_mapping = {
        "account_name": "Acct",
        "statement_date": "Stmnt Date",
        "closing_balance": "End Bal",
        "available_balance": "Clear Bal",
        "currency": "Ccy"
    }

    result = await BankBalanceParser.parse_and_store(content, client_id, "test.csv", db, column_mapping)

    assert result["rows_valid"] == 1
    assert result["rows_failed"] == 0
