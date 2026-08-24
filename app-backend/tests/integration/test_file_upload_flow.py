"""
Integration tests for file upload flow.
Covers CSV, BAI2, camt.053, MT940 formats.
"""
import pytest
import httpx
from io import BytesIO
from datetime import date
from tests.jwt_helper import make_treasury_manager_token


@pytest.fixture
async def http_client():
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        yield client


@pytest.mark.asyncio
class TestFileUploadFlow:
    """Test file upload and parsing."""

    async def test_csv_upload_valid(self, http_client):
        """
        Upload a 3-row CSV with valid data.
        Assert: 200 or 207
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        today = date.today().isoformat()
        csv_content = (
            "account_number,date,description,credit,debit,currency\n"
            f"GB29NWBK60161331926819,{today},Test credit,10000,,GBP\n"
            f"GB29NWBK60161331926819,{today},Test debit,,5000,GBP\n"
            f"GB29NWBK60161331926819,{today},Another credit,2500,,GBP\n"
        )

        files = {
            "file": ("test.csv", BytesIO(csv_content.encode()), "text/csv"),
        }
        data = {
            "entity_id": "entity-test-001",
        }

        response = await http_client.post(
            "/api/files/upload",
            files=files,
            data=data,
            headers=headers,
        )

        assert response.status_code in [200, 207], \
            f"Expected 200 or 207, got {response.status_code}: {response.text}"

    async def test_file_too_large(self, http_client):
        """
        Upload a file >10MB.
        Assert: 413
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create 10.5MB file
        large_content = b"x" * (10_500_000)
        files = {
            "file": ("large.csv", BytesIO(large_content), "text/csv"),
        }
        data = {"entity_id": "entity-test-001"}

        response = await http_client.post(
            "/api/files/upload",
            files=files,
            data=data,
            headers=headers,
        )

        assert response.status_code == 413, \
            f"Expected 413, got {response.status_code}"

    async def test_excel_rejected(self, http_client):
        """
        Upload .xlsx file.
        Assert: 400 with VALIDATION_UNSUPPORTED_FORMAT
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        files = {
            "file": ("data.xlsx", BytesIO(b"mock xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        }
        data = {"entity_id": "entity-test-001"}

        response = await http_client.post(
            "/api/files/upload",
            files=files,
            data=data,
            headers=headers,
        )

        assert response.status_code == 400
        error = response.json()
        assert error.get("error", {}).get("code") == "VALIDATION_UNSUPPORTED_FORMAT"

    async def test_bai2_upload(self, http_client):
        """
        Upload minimal BAI2 file.
        Assert: 200 or 207
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        bai2_content = (
            "01,TESTBANK,TESTCORP,220101,1200,1,80,2/\n"
            "02,TESTCORP,TESTBANK,1,220101,,2/\n"
            "03,GB29NWBK60161331926819,GBP,2,500000,,/\n"
            "16,115,100000,220101,,Test credit/\n"
            "16,451,50000,220101,,Test debit/\n"
            "49,550000,2/\n"
            "98,550000,1,2/\n"
            "99,550000,1,2/\n"
        )

        files = {
            "file": ("statement.bai2", BytesIO(bai2_content.encode()), "text/plain"),
        }
        data = {"entity_id": "entity-test-001"}

        response = await http_client.post(
            "/api/files/upload",
            files=files,
            data=data,
            headers=headers,
        )

        assert response.status_code in [200, 207], \
            f"Expected 200 or 207, got {response.status_code}: {response.text}"

    async def test_camt053_upload(self, http_client):
        """
        Upload minimal camt.053 XML.
        Assert: 200 or 207
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        camt053_content = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.002.02">
  <BkStmt>
    <Acct>
      <Id>GB29NWBK60161331926819</Id>
      <Ccy>GBP</Ccy>
    </Acct>
    <Ntry>
      <Amt>100000</Amt>
      <CdtDbtInd>CRDT</CdtDbtInd>
    </Ntry>
    <Ntry>
      <Amt>50000</Amt>
      <CdtDbtInd>DBIT</CdtDbtInd>
    </Ntry>
  </BkStmt>
</Document>
"""

        files = {
            "file": ("statement.xml", BytesIO(camt053_content), "application/xml"),
        }
        data = {"entity_id": "entity-test-001"}

        response = await http_client.post(
            "/api/files/upload",
            files=files,
            data=data,
            headers=headers,
        )

        assert response.status_code in [200, 207], \
            f"Expected 200 or 207, got {response.status_code}: {response.text}"

    async def test_mt940_upload(self, http_client):
        """
        Upload minimal MT940 file.
        Assert: 200 or 207
        """
        token = make_treasury_manager_token()
        headers = {"Authorization": f"Bearer {token}"}

        mt940_content = """{1:F01TESTBANK0XXXX0000000000}
{2:I940TESTCORP0XXXX0000000000}
{3:{113:GBPA}{108:2024010112345678}}
{4:
:20:12345
:25:GB29NWBK60161331926819
:28C:0/1
:60F:C240101GBP500000,00
:61:2401011201CR100000,00NSTO
:86:1111 Test credit
:61:2401021201DR50000,00NSTO
:86:1111 Test debit
:62F:C240102GBP550000,00
-}
"""

        files = {
            "file": ("statement.txt", BytesIO(mt940_content.encode()), "text/plain"),
        }
        data = {"entity_id": "entity-test-001"}

        response = await http_client.post(
            "/api/files/upload",
            files=files,
            data=data,
            headers=headers,
        )

        assert response.status_code in [200, 207], \
            f"Expected 200 or 207, got {response.status_code}: {response.text}"

    async def test_file_upload_unauthenticated_returns_401(self, http_client):
        """POST /api/files/upload without token returns 401."""
        files = {
            "file": ("test.csv", BytesIO(b"test"), "text/csv"),
        }
        data = {"entity_id": "entity-test-001"}

        response = await http_client.post(
            "/api/files/upload",
            files=files,
            data=data,
        )

        assert response.status_code == 401
