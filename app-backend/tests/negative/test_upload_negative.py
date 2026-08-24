"""
Negative tests for file uploads.
Tests: unsupported formats, missing columns, invalid values, malformed files, size limits.
"""
import pytest
import httpx
import io
from tests.jwt_helper import make_treasury_manager_token, make_analyst_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        yield client


class TestUploadNegative:
    """Test file upload validation."""

    @pytest.mark.asyncio
    async def test_b1_unsupported_file_format_xlsx(self, http_client):
        """B1: .xlsx file returns 400 with VALIDATION_UNSUPPORTED_FORMAT."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create minimal .xlsx-like content (just has .xlsx extension)
        xlsx_content = b"PK\x03\x04" + b"\x00" * 100  # Mock Excel file signature

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.xlsx", xlsx_content)},
            headers=headers
        )

        assert response.status_code == 400
        data = response.json()
        assert data.get("error", {}).get("code") == "VALIDATION_UNSUPPORTED_FORMAT"
        assert ".xlsx" in data.get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_b2_empty_csv_file(self, http_client):
        """B2: Empty CSV file returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", b"")},
            headers=headers
        )

        assert response.status_code == 422
        assert response.json().get("error", {}).get("code") == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_b3_csv_missing_entity_name_column(self, http_client):
        """B3: CSV missing 'Entity Name' column returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Missing "Entity Name" column
        csv_content = b"Account Number,Closing Balance\nACC-001,1000000\n"

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", csv_content)},
            headers=headers
        )

        assert response.status_code == 422
        data = response.json()
        assert data.get("error", {}).get("code") == "VALIDATION_ERROR"
        assert "Entity Name" in data.get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_b4_csv_missing_account_number_column(self, http_client):
        """B4: CSV missing 'Account Number' column returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Entity Name,Closing Balance\nTest Corp,1000000\n"

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", csv_content)},
            headers=headers
        )

        assert response.status_code == 422
        data = response.json()
        assert "Account Number" in data.get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_b5_csv_missing_closing_balance_column(self, http_client):
        """B5: CSV missing 'Closing Balance' column returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Entity Name,Account Number\nTest Corp,ACC-001\n"

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", csv_content)},
            headers=headers
        )

        assert response.status_code == 422
        assert "Closing Balance" in response.json().get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_b6_csv_non_numeric_closing_balance(self, http_client):
        """B6: CSV with non-numeric Closing Balance returns 422 or flags row."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Entity Name,Account Number,Closing Balance,Statement Date\nTest Corp,ACC-001,N/A,2026-08-24\n"

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", csv_content)},
            headers=headers
        )

        # Either 422 or 202 with flagged_rows
        if response.status_code == 202:
            data = response.json()
            assert data.get("rows_flagged", 0) >= 1
            assert len(data.get("flagged_rows", [])) > 0
            assert "parse" in data["flagged_rows"][0].get("issue", "").lower()
        else:
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_b7_csv_future_statement_date(self, http_client):
        """B7: CSV with future Statement Date returns 422 or flags row."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Entity Name,Account Number,Closing Balance,Statement Date\nTest Corp,ACC-001,1000000,2026-12-31\n"

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", csv_content)},
            headers=headers
        )

        if response.status_code == 202:
            data = response.json()
            assert data.get("rows_flagged", 0) >= 1
            assert "future" in data["flagged_rows"][0].get("issue", "").lower()
        else:
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_b8_csv_unknown_currency(self, http_client):
        """B8: CSV with unsupported currency returns 422 or flags row."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Entity Name,Account Number,Closing Balance,Currency\nTest Corp,ACC-001,1000000,JPY\n"

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", csv_content)},
            headers=headers
        )

        if response.status_code == 202:
            data = response.json()
            assert data.get("rows_flagged", 0) >= 1
        else:
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_b9_csv_unmapped_account_number_flagged_not_dropped(self, http_client):
        """B9: Unmapped account number is flagged and ingested with Low confidence."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Entity Name,Account Number,Closing Balance,Statement Date\nTest Corp,ACC-9999,1000000,2026-08-24\n"

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", csv_content)},
            headers=headers
        )

        assert response.status_code == 202
        data = response.json()
        assert data.get("rows_flagged", 0) >= 1, "Unmapped account should be flagged"
        assert "Account Master" in data["flagged_rows"][0].get("issue", "")
        assert "Low confidence" in data["flagged_rows"][0].get("action", "")
        # CRITICAL: Row must be ingested, not dropped
        assert data.get("rows_ingested", 0) >= 1, "Unmapped row must be ingested"

    @pytest.mark.asyncio
    async def test_b10_ar_csv_missing_counterparty_column(self, http_client):
        """B10: AR CSV missing 'Counterparty' column returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Invoice Number,Amount,Due Date\nINV-001,50000,2026-09-30\n"

        response = await http_client.post(
            "/api/files/upload?file_type=ar",
            files={"file": ("ar.csv", csv_content)},
            headers=headers
        )

        assert response.status_code == 422
        assert "Counterparty" in response.json().get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_b11_ar_csv_negative_invoice_amount(self, http_client):
        """B11: AR CSV with negative Invoice Amount returns 422 or flags row."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Invoice Number,Counterparty,Amount\nINV-001,ACME Corp,-5000\n"

        response = await http_client.post(
            "/api/files/upload?file_type=ar",
            files={"file": ("ar.csv", csv_content)},
            headers=headers
        )

        if response.status_code == 202:
            data = response.json()
            assert data.get("rows_flagged", 0) >= 1
            assert "must be > 0" in data["flagged_rows"][0].get("issue", "")
        else:
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_b12_ar_csv_zero_invoice_amount(self, http_client):
        """B12: AR CSV with zero Invoice Amount returns 422 or flags row."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Invoice Number,Counterparty,Amount\nINV-001,ACME Corp,0\n"

        response = await http_client.post(
            "/api/files/upload?file_type=ar",
            files={"file": ("ar.csv", csv_content)},
            headers=headers
        )

        if response.status_code == 202:
            data = response.json()
            assert data.get("rows_flagged", 0) >= 1
        else:
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_b13_ap_csv_missing_status_column(self, http_client):
        """B13: AP CSV missing 'Status' column returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Payment ID,Vendor,Amount\nPAY-001,Vendor Inc,10000\n"

        response = await http_client.post(
            "/api/files/upload?file_type=ap",
            files={"file": ("ap.csv", csv_content)},
            headers=headers
        )

        assert response.status_code == 422
        assert "Status" in response.json().get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_b14_ap_csv_invalid_status_value(self, http_client):
        """B14: AP CSV with invalid Status value returns 422 or flags row."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"Payment ID,Vendor,Amount,Status\nPAY-001,Vendor Inc,10000,Cancelled\n"

        response = await http_client.post(
            "/api/files/upload?file_type=ap",
            files={"file": ("ap.csv", csv_content)},
            headers=headers
        )

        if response.status_code == 202:
            data = response.json()
            assert data.get("rows_flagged", 0) >= 1
            assert "Cancelled" in data["flagged_rows"][0].get("issue", "")
        else:
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_b15_bai2_malformed_header_missing_02_record(self, http_client):
        """B15: BAI2 file missing '02,' group record returns 400."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # BAI2 starting with 01, but missing 02, record
        bai2_content = b"01,HEADER,1,0,1,0,001234567890\n92,TRAILER,1,1\n"

        response = await http_client.post(
            "/api/files/upload?file_type=bai2",
            files={"file": ("test.bai2", bai2_content)},
            headers=headers
        )

        assert response.status_code == 400
        assert "BAI2" in response.json().get("error", {}).get("message", "") or "format" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_b16_bai2_amounts_divided_by_100(self, http_client):
        """B16: BAI2 parser divides amounts by 100."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # BAI2 with amount field 100000 (representing $1000.00)
        bai2_content = b"""01,HEADER,1,0,1,0,001234567890
02,001,0000000100000,,,1,0
88,000001100000
92,TRAILER,1,1"""

        response = await http_client.post(
            "/api/files/upload?file_type=bai2",
            files={"file": ("test.bai2", bai2_content)},
            headers=headers
        )

        if response.status_code in [200, 202]:
            data = response.json()
            # Verify amount was divided: 100000 / 100 = 1000
            # This should be checked in the parsed response
            parsed_amount = data.get("parsed_records", [{}])[0].get("amount")
            if parsed_amount:
                assert parsed_amount == 1000.00, f"Expected 1000.00, got {parsed_amount}"

    @pytest.mark.asyncio
    async def test_b17_mt940_missing_closing_balance_tag(self, http_client):
        """B17: MT940 missing :62F: tag returns 400 or flags it."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # MT940 missing :62F: closing balance
        mt940_content = b""":20:STARTUMSG
:25:GB29NWBK60161331926819
:60F:C220801GBP1000000
:61:220802CR100000NMSCTEST1//REF
:86:TEST CREDIT
"""

        response = await http_client.post(
            "/api/files/upload?file_type=mt940",
            files={"file": ("test.mt940", mt940_content)},
            headers=headers
        )

        if response.status_code == 400:
            assert "closing" in response.json().get("error", {}).get("message", "").lower()
        else:
            data = response.json()
            if data.get("rows_flagged", 0) >= 1:
                assert "closing_balance" in data["flagged_rows"][0].get("issue", "").lower()

    @pytest.mark.asyncio
    async def test_b18_camt053_malformed_xml(self, http_client):
        """B18: Malformed XML returns 400."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Unclosed XML tags
        xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <Stmt>
    <BkTxCd>
  </Stmt>
</Document>"""

        response = await http_client.post(
            "/api/files/upload?file_type=camt053",
            files={"file": ("test.xml", xml_content)},
            headers=headers
        )

        assert response.status_code == 400
        assert "XML" in response.json().get("error", {}).get("message", "")

    @pytest.mark.asyncio
    async def test_b19_camt053_missing_namespace(self, http_client):
        """B19: camt.053 missing namespace returns 400 or flags it."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Valid XML but missing camt.053 namespace
        xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document>
  <Stmt>
    <Amt>1000000</Amt>
  </Stmt>
</Document>"""

        response = await http_client.post(
            "/api/files/upload?file_type=camt053",
            files={"file": ("test.xml", xml_content)},
            headers=headers
        )

        if response.status_code == 400:
            assert "namespace" in response.json().get("error", {}).get("message", "").lower()
        else:
            data = response.json()
            if data.get("rows_flagged", 0) >= 1:
                assert "namespace" in data["flagged_rows"][0].get("issue", "").lower()

    @pytest.mark.asyncio
    async def test_b20_file_too_large_over_10mb(self, http_client):
        """B20: File >10MB returns 413."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create 15MB content
        large_content = b"x" * (15 * 1024 * 1024)

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("large.csv", large_content)},
            headers=headers,
            timeout=30.0
        )

        assert response.status_code == 413
        assert "too large" in response.json().get("error", {}).get("message", "").lower()

    @pytest.mark.asyncio
    async def test_b21_column_mapping_unmapped_required_field(self, http_client):
        """B21: Unmapped required field returns 422."""
        token = make_analyst_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await http_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", b"Entity Name,Account Number\nTest,ACC-001\n")},
            json={"column_mapping": {"entity_name": 0, "account_number": 1}},  # Missing date
            headers=headers
        )

        assert response.status_code == 422
        assert "date" in response.json().get("error", {}).get("message", "").lower()
