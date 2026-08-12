from decimal import Decimal
from pathlib import Path

import pytest

from app.infra.iso20022.pain001 import Pain001ParseError, parse_pain001

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def test_parses_valid_pain001_fixture() -> None:
    transfer = parse_pain001(_load("pain001_valid.xml"))

    assert transfer.message_id == "MSG-0001"
    assert transfer.end_to_end_id == "E2E-0001"
    assert transfer.debtor_account_number == "SG-D-0001"
    assert transfer.creditor_account_number == "SG-C-0001"
    assert transfer.amount == Decimal("20.00")
    assert transfer.currency == "SGD"


def test_malformed_xml_raises_parse_error() -> None:
    with pytest.raises(Pain001ParseError, match="malformed XML"):
        parse_pain001(_load("pain001_malformed.xml"))


def test_missing_required_field_raises_parse_error() -> None:
    with pytest.raises(Pain001ParseError, match="Amt/InstdAmt"):
        parse_pain001(_load("pain001_missing_field.xml"))


def test_missing_currency_attribute_raises_parse_error() -> None:
    xml = b"""<?xml version="1.0"?>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
      <CstmrCdtTrfInitn>
        <GrpHdr><MsgId>M</MsgId></GrpHdr>
        <PmtInf>
          <DbtrAcct><Id><Othr><Id>D</Id></Othr></Id></DbtrAcct>
          <CdtTrfTxInf>
            <PmtId><EndToEndId>E</EndToEndId></PmtId>
            <Amt><InstdAmt>20.00</InstdAmt></Amt>
            <CdtrAcct><Id><Othr><Id>C</Id></Othr></Id></CdtrAcct>
          </CdtTrfTxInf>
        </PmtInf>
      </CstmrCdtTrfInitn>
    </Document>"""
    with pytest.raises(Pain001ParseError, match="Ccy"):
        parse_pain001(xml)


def test_invalid_amount_text_raises_parse_error() -> None:
    xml = b"""<?xml version="1.0"?>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
      <CstmrCdtTrfInitn>
        <GrpHdr><MsgId>M</MsgId></GrpHdr>
        <PmtInf>
          <DbtrAcct><Id><Othr><Id>D</Id></Othr></Id></DbtrAcct>
          <CdtTrfTxInf>
            <PmtId><EndToEndId>E</EndToEndId></PmtId>
            <Amt><InstdAmt Ccy="SGD">not-a-number</InstdAmt></Amt>
            <CdtrAcct><Id><Othr><Id>C</Id></Othr></Id></CdtrAcct>
          </CdtTrfTxInf>
        </PmtInf>
      </CstmrCdtTrfInitn>
    </Document>"""
    with pytest.raises(Pain001ParseError, match="invalid amount"):
        parse_pain001(xml)


def test_doctype_declaration_is_rejected_outright() -> None:
    xml = b"""<?xml version="1.0"?>
    <!DOCTYPE Document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
      <CstmrCdtTrfInitn/>
    </Document>"""
    with pytest.raises(Pain001ParseError, match="DOCTYPE"):
        parse_pain001(xml)


def test_external_entity_reference_is_neutralised_even_if_doctype_check_is_bypassed(
    tmp_path,
) -> None:
    """Defense-in-depth: parse_pain001 rejects any DOCTYPE outright (tested above), but
    this proves the deeper mitigation — the parser's resolve_entities=False — also holds
    on its own. Confirmed empirically: lxml does not error and does not fetch the file;
    the entity reference simply resolves to no text at all.
    """
    from lxml import etree

    from app.infra.iso20022.pain001 import _XML_PARSER

    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("super-secret-contents")
    xml = f"""<?xml version="1.0"?>
    <!DOCTYPE Document [<!ENTITY xxe SYSTEM "file:///{secret_file.as_posix()}">]>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
      <CstmrCdtTrfInitn>
        <GrpHdr><MsgId>&xxe;</MsgId></GrpHdr>
      </CstmrCdtTrfInitn>
    </Document>""".encode()

    root = etree.fromstring(xml, parser=_XML_PARSER)
    msg_id = root.find(".//{urn:iso:std:iso:20022:tech:xsd:pain.001.001.09}MsgId")
    assert msg_id.text is None
    assert b"super-secret-contents" not in etree.tostring(root)
