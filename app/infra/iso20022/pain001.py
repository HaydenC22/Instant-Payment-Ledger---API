from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from lxml import etree

PAIN001_NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
_NSMAP = {"ns": PAIN001_NAMESPACE}

# XXE hardening: no DTD loading, no entity resolution, no network access. lxml's defaults
# are not safe for untrusted input (the library predates XXE being widely understood as a
# vulnerability class), so this has to be set explicitly rather than relying on defaults —
# defusedxml's lxml wrapper is deprecated upstream, so this project hardens lxml directly.
_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    dtd_validation=False,
    load_dtd=False,
    huge_tree=False,
)


class Pain001ParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Pain001CreditTransfer:
    message_id: str
    end_to_end_id: str
    debtor_account_number: str
    creditor_account_number: str
    amount: Decimal
    currency: str


def parse_pain001(xml_bytes: bytes) -> Pain001CreditTransfer:
    """Parses the fields this API needs from a pain.001.001.09 CustomerCreditTransferInitiation
    message.

    Deliberately partial, matching the scope of this project's ISO 20022 support: reads the
    first credit transfer transaction from the first payment instruction, not the full
    multi-transaction batch structure or optional blocks (charges, remittance info,
    ultimate debtor/creditor, purpose codes, etc.).
    """
    if b"<!DOCTYPE" in xml_bytes:
        # Belt-and-braces: resolve_entities=False below already prevents an external
        # entity from being expanded (confirmed — it resolves to empty text, not the
        # referenced file's contents, and not an error either), but a legitimate pain.001
        # message never carries a DOCTYPE, so reject it outright rather than silently
        # parse-and-ignore.
        raise Pain001ParseError("DOCTYPE declarations are not permitted")

    try:
        root = etree.fromstring(xml_bytes, parser=_XML_PARSER)
    except etree.XMLSyntaxError as exc:
        raise Pain001ParseError(f"malformed XML: {exc}") from exc

    def find_text(path: str) -> str | None:
        el = root.find(path, namespaces=_NSMAP)
        return el.text.strip() if el is not None and el.text else None

    message_id = find_text(".//ns:GrpHdr/ns:MsgId")
    end_to_end_id = find_text(".//ns:PmtInf/ns:CdtTrfTxInf/ns:PmtId/ns:EndToEndId")
    debtor_account_number = find_text(".//ns:PmtInf/ns:DbtrAcct/ns:Id/ns:Othr/ns:Id")
    creditor_account_number = find_text(
        ".//ns:PmtInf/ns:CdtTrfTxInf/ns:CdtrAcct/ns:Id/ns:Othr/ns:Id"
    )
    amount_el = root.find(".//ns:PmtInf/ns:CdtTrfTxInf/ns:Amt/ns:InstdAmt", namespaces=_NSMAP)

    missing = [
        name
        for name, value in [
            ("GrpHdr/MsgId", message_id),
            ("PmtId/EndToEndId", end_to_end_id),
            ("DbtrAcct/Id/Othr/Id", debtor_account_number),
            ("CdtrAcct/Id/Othr/Id", creditor_account_number),
        ]
        if not value
    ]
    if amount_el is None or not (amount_el.text and amount_el.text.strip()):
        missing.append("Amt/InstdAmt")
    if missing:
        raise Pain001ParseError(f"missing required field(s): {', '.join(missing)}")

    currency = amount_el.get("Ccy")
    if not currency:
        raise Pain001ParseError("Amt/InstdAmt is missing the required Ccy attribute")

    try:
        amount = Decimal(amount_el.text.strip())
    except InvalidOperation as exc:
        raise Pain001ParseError(f"invalid amount: {amount_el.text!r}") from exc

    assert message_id is not None
    assert end_to_end_id is not None
    assert debtor_account_number is not None
    assert creditor_account_number is not None

    return Pain001CreditTransfer(
        message_id=message_id,
        end_to_end_id=end_to_end_id,
        debtor_account_number=debtor_account_number,
        creditor_account_number=creditor_account_number,
        amount=amount,
        currency=currency,
    )
