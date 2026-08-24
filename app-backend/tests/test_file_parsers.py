import uuid
from datetime import date

import pytest

from app.services.file_format_detector import detect_format
from app.services.file_parsers.bai2_parser import BAI2Parser
from app.services.file_parsers.camt053_parser import Camt053Parser
from app.services.file_parsers.mt940_parser import MT940Parser


# ─────────────────────────────────────────
# Format Detection Tests
# ─────────────────────────────────────────


class TestFormatDetection:
    def test_detect_bai2_from_content(self):
        content = b"01,094101,1234567890,060421,0800,1,0,\n"
        fmt = detect_format("bank_file.txt", content)
        assert fmt == "BAI2"

    def test_detect_mt940_from_content(self):
        content = b":20:STARTUMTYPE\n"
        fmt = detect_format("bank_file.txt", content)
        assert fmt == "MT940"

    def test_detect_camt053_from_xml_extension(self):
        content = b"<?xml version=\"1.0\"?><Document></Document>"
        fmt = detect_format("bank_file.xml", content)
        assert fmt == "CAMT053"

    def test_detect_csv_from_extension(self):
        content = b"Date,Amount,Description\n2026-08-01,1000,Test"
        fmt = detect_format("data.csv", content)
        assert fmt == "CSV"

    def test_detect_csv_uppercase(self):
        fmt = detect_format("data.CSV", b"content")
        assert fmt == "CSV"

    def test_detect_unknown(self):
        content = b"Some random content"
        fmt = detect_format("file.txt", content)
        assert fmt == "UNKNOWN"

    def test_detection_order_xml_first(self):
        # XML extension takes priority
        content = b"01,header"
        fmt = detect_format("file.xml", content)
        assert fmt == "CAMT053"


# ─────────────────────────────────────────
# BAI2 Parser Tests
# ─────────────────────────────────────────


class TestBAI2Parser:
    def setup_method(self):
        self.parser = BAI2Parser()
        self.entity_id = str(uuid.uuid4())

    def test_parse_minimal_valid_bai2(self):
        content = b"""01,094101,1234567890,060421,0800,1,0,
02,094101,1234567890,1,0,
03,121000248,US001,USD,
16,060421,115,150000,
16,060421,451,75000,
49,2,150000,0,0,
98,1,1,1,225000
99,1,1,"""
        rows = self.parser.parse(content, self.entity_id)
        assert len(rows) == 2
        assert rows[0].source_format == "BAI2"
        assert rows[0].credit_amount == 1500.00
        assert rows[1].debit_amount == 750.00

    def test_bai2_type_code_credit(self):
        # Type code 115 (credit)
        content = b"""01,094101,1234567890,060421,0800,1,0,
02,094101,1234567890,1,0,
03,121000248,US001,USD,
16,060421,115,150000,
49,2,150000,0,0,
98,1,1,1,150000
99,1,1,"""
        rows = self.parser.parse(content, self.entity_id)
        assert len(rows) == 1
        assert rows[0].credit_amount == 1500.00
        assert rows[0].debit_amount is None

    def test_bai2_type_code_debit(self):
        # Type code 451 (debit)
        content = b"""01,094101,1234567890,060421,0800,1,0,
02,094101,1234567890,1,0,
03,121000248,US001,USD,
16,060421,451,75000,
49,2,75000,0,0,
98,1,1,1,75000
99,1,1,"""
        rows = self.parser.parse(content, self.entity_id)
        assert len(rows) == 1
        assert rows[0].debit_amount == 750.00
        assert rows[0].credit_amount is None

    def test_bai2_amount_conversion(self):
        # 150000 cents = 1500.00
        content = b"""01,094101,1234567890,060421,0800,1,0,
02,094101,1234567890,1,0,
03,121000248,US001,USD,
16,060421,115,150000,
49,2,150000,0,0,
98,1,1,1,150000
99,1,1,"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].credit_amount == 1500.00

    def test_bai2_continuation_record(self):
        # 88, continuation record
        content = b"""01,094101,1234567890,060421,0800,1,0,
02,094101,1234567890,1,0,
03,121000248,US001,USD,
16,060421,115,150000,Description part 1
88, Description part 2
49,2,150000,0,0,
98,1,1,1,150000
99,1,1,"""
        rows = self.parser.parse(content, self.entity_id)
        assert len(rows) == 1
        assert "Description part 1" in rows[0].description
        assert "Description part 2" in rows[0].description

    def test_bai2_date_parsing_2022(self):
        # 220101 → 2022-01-01
        content = b"""01,094101,1234567890,060421,0800,1,0,
02,094101,1234567890,1,0,
03,121000248,US001,USD,
16,220101,115,150000,
49,2,150000,0,0,
98,1,1,1,150000
99,1,1,"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].transaction_date == date(2022, 1, 1)

    def test_bai2_date_parsing_1999(self):
        # 991231 → 1999-12-31
        content = b"""01,094101,1234567890,060421,0800,1,0,
02,094101,1234567890,1,0,
03,121000248,US001,USD,
16,991231,115,150000,
49,2,150000,0,0,
98,1,1,1,150000
99,1,1,"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].transaction_date == date(1999, 12, 31)

    def test_bai2_missing_header(self):
        content = b"""02,094101,1234567890,1,0,
03,121000248,US001,USD,"""
        with pytest.raises(ValueError, match="BAI2 header missing"):
            self.parser.parse(content, self.entity_id)

    def test_bai2_unknown_type_code_skipped(self):
        # Type code 999 is unknown
        content = b"""01,094101,1234567890,060421,0800,1,0,
02,094101,1234567890,1,0,
03,121000248,US001,USD,
16,060421,999,150000,
49,2,0,0,0,
98,1,1,1,0
99,1,1,"""
        rows = self.parser.parse(content, self.entity_id)
        assert len(rows) == 1
        assert rows[0].debit_amount is None
        assert rows[0].credit_amount is None
        assert rows[0].raw_type_code == "999"


# ─────────────────────────────────────────
# camt.053 Parser Tests
# ─────────────────────────────────────────


class TestCamt053Parser:
    def setup_method(self):
        self.parser = Camt053Parser()
        self.entity_id = str(uuid.uuid4())

    def test_parse_minimal_valid_camt053(self):
        xml_content = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.002.02">
  <BkToCstmrStmt>
    <Stmt>
      <Acct>
        <Id>
          <IBAN>DE89370400440532013000</IBAN>
        </Id>
        <Ccy>EUR</Ccy>
      </Acct>
      <Ntry>
        <BookgDt><Dt>2026-08-21</Dt></BookgDt>
        <Amt>1500.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <NtryDtls>
          <TxDtls>
            <RmtInf><Ustrd>Payment received</Ustrd></RmtInf>
          </TxDtls>
        </NtryDtls>
      </Ntry>
      <Ntry>
        <BookgDt><Dt>2026-08-22</Dt></BookgDt>
        <Amt>750.00</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        rows = self.parser.parse(xml_content, self.entity_id)
        assert len(rows) == 2
        assert rows[0].credit_amount == 1500.00
        assert rows[1].debit_amount == 750.00
        assert rows[0].source_format == "CAMT053"

    def test_camt053_credit_entry(self):
        xml_content = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.002.02">
  <BkToCstmrStmt>
    <Stmt>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id><Ccy>EUR</Ccy></Acct>
      <Ntry>
        <BookgDt><Dt>2026-08-21</Dt></BookgDt>
        <Amt>1500.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        rows = self.parser.parse(xml_content, self.entity_id)
        assert rows[0].credit_amount == 1500.00
        assert rows[0].debit_amount is None

    def test_camt053_debit_entry(self):
        xml_content = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.002.02">
  <BkToCstmrStmt>
    <Stmt>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id><Ccy>EUR</Ccy></Acct>
      <Ntry>
        <BookgDt><Dt>2026-08-21</Dt></BookgDt>
        <Amt>750.00</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        rows = self.parser.parse(xml_content, self.entity_id)
        assert rows[0].debit_amount == 750.00
        assert rows[0].credit_amount is None

    def test_camt053_namespace_aware(self):
        # Without namespace prefix
        xml_content = b"""<?xml version="1.0"?>
<Document>
  <BkToCstmrStmt>
    <Stmt>
      <Acct><Id><IBAN>GB82WEST12345698765432</IBAN></Id><Ccy>GBP</Ccy></Acct>
      <Ntry>
        <BookgDt><Dt>2026-08-21</Dt></BookgDt>
        <Amt>2000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        rows = self.parser.parse(xml_content, self.entity_id)
        assert len(rows) == 1
        assert rows[0].currency == "GBP"

    def test_camt053_missing_booking_date(self):
        xml_content = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.002.02">
  <BkToCstmrStmt>
    <Stmt>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id><Ccy>EUR</Ccy></Acct>
      <Ntry>
        <Amt>1500.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        with pytest.raises(ValueError, match="no valid transactions"):
            self.parser.parse(xml_content, self.entity_id)

    def test_camt053_invalid_xml(self):
        with pytest.raises(ValueError, match="Invalid XML"):
            self.parser.parse(b"Not valid XML", self.entity_id)


# ─────────────────────────────────────────
# MT940 Parser Tests
# ─────────────────────────────────────────


class TestMT940Parser:
    def setup_method(self):
        self.parser = MT940Parser()
        self.entity_id = str(uuid.uuid4())

    def test_parse_minimal_valid_mt940(self):
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:28C:00000/001
:60F:C260821GBP10000,00
:61:260821C2500,00TRANSACTIONCODE
:86:Payment received from Customer A
:61:260822D1000,00TRANSACTIONCODE
:86:Payment to Vendor B
:62F:C260822GBP11500,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert len(rows) == 2
        assert rows[0].credit_amount == 2500.00
        assert rows[1].debit_amount == 1000.00
        assert rows[0].source_format == "MT940"

    def test_mt940_credit_indicator(self):
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:60F:C260821GBP10000,00
:61:260821C1500,00TRX
:62F:C260821GBP11500,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].credit_amount == 1500.00
        assert rows[0].debit_amount is None

    def test_mt940_debit_indicator(self):
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:60F:C260821GBP10000,00
:61:260821D750,00TRX
:62F:C260821GBP9250,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].debit_amount == 750.00
        assert rows[0].credit_amount is None

    def test_mt940_reversal_credit(self):
        # RC = reversal of debit (credit)
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:60F:C260821GBP10000,00
:61:260821RC1000,00TRX
:62F:C260821GBP11000,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].credit_amount == 1000.00

    def test_mt940_reversal_debit(self):
        # RD = reversal of credit (debit)
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:60F:C260821GBP10000,00
:61:260821RD1000,00TRX
:62F:C260821GBP9000,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].debit_amount == 1000.00

    def test_mt940_amount_conversion(self):
        # 1500,00 → 1500.00
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:60F:C260821GBP10000,00
:61:260821C1500,00TRX
:62F:C260821GBP11500,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].credit_amount == 1500.00

    def test_mt940_balance_after_last_only(self):
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:60F:C260821GBP10000,00
:61:260821C1500,00TRX
:61:260821D750,00TRX
:62F:C260821GBP10750,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].balance_after is None
        assert rows[1].balance_after == 10750.00

    def test_mt940_date_parsing_2022(self):
        # 220101 → 2022-01-01
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:60F:C220101GBP10000,00
:61:220101C1500,00TRX
:62F:C220101GBP11500,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].transaction_date == date(2022, 1, 1)

    def test_mt940_missing_account(self):
        content = b""":20:STARTUMTYPE
:28C:00000/001
:60F:C260821GBP10000,00
:61:260821C1500,00TRX"""
        with pytest.raises(ValueError, match="account identifier missing"):
            self.parser.parse(content, self.entity_id)

    def test_mt940_currency_from_opening_balance(self):
        # Currency code from :60F: line
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432
:60F:C260821EUR5000,00
:61:260821C1500,00TRX
:62F:C260821EUR6500,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].currency == "EUR"

    def test_mt940_account_with_currency_suffix(self):
        # Account with /currency suffix should be stripped
        content = b""":20:STARTUMTYPE
:25:GB82WEST12345698765432/GBP
:60F:C260821GBP10000,00
:61:260821C1500,00TRX
:62F:C260821GBP11500,00"""
        rows = self.parser.parse(content, self.entity_id)
        assert rows[0].account_number_raw == "GB82WEST12345698765432"
