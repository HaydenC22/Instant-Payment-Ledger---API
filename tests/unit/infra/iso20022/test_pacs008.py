from decimal import Decimal
from uuid import uuid4

import pytest
from lxml import etree

from app.domain.payments.entities import Payment, PaymentStatus
from app.infra.iso20022.pacs008 import PACS008_NAMESPACE, Pacs008EmissionError, build_pacs008

_NSMAP = {"ns": PACS008_NAMESPACE}


def _settled_payment(**overrides) -> Payment:
    defaults = dict(
        id=uuid4(),
        debtor_account_id=uuid4(),
        creditor_account_id=uuid4(),
        amount=Decimal("42.50"),
        currency="SGD",
        status=PaymentStatus.SETTLED,
        version=2,
        end_to_end_id="E2E-9001",
    )
    return Payment(**{**defaults, **overrides})


def test_build_pacs008_round_trips_all_fields() -> None:
    payment = _settled_payment()

    xml_bytes = build_pacs008(
        payment,
        debtor_account_number="SG-D-01",
        debtor_name="Alice Tan",
        creditor_account_number="SG-C-01",
        creditor_name="Bob Lee",
    )

    root = etree.fromstring(xml_bytes)
    assert root.find(".//ns:CdtTrfTxInf/ns:PmtId/ns:EndToEndId", _NSMAP).text == "E2E-9001"
    assert root.find(".//ns:CdtTrfTxInf/ns:PmtId/ns:TxId", _NSMAP).text == str(payment.id)

    amt_el = root.find(".//ns:CdtTrfTxInf/ns:IntrBkSttlmAmt", _NSMAP)
    assert amt_el.text == "42.50"
    assert amt_el.get("Ccy") == "SGD"

    assert root.find(".//ns:CdtTrfTxInf/ns:Dbtr/ns:Nm", _NSMAP).text == "Alice Tan"
    assert root.find(".//ns:CdtTrfTxInf/ns:DbtrAcct/ns:Id/ns:Othr/ns:Id", _NSMAP).text == "SG-D-01"
    assert root.find(".//ns:CdtTrfTxInf/ns:Cdtr/ns:Nm", _NSMAP).text == "Bob Lee"
    assert root.find(".//ns:CdtTrfTxInf/ns:CdtrAcct/ns:Id/ns:Othr/ns:Id", _NSMAP).text == "SG-C-01"
    assert root.find(".//ns:GrpHdr/ns:NbOfTxs", _NSMAP).text == "1"


def test_build_pacs008_uses_payment_id_as_end_to_end_id_when_absent() -> None:
    payment = _settled_payment(end_to_end_id=None)

    xml_bytes = build_pacs008(
        payment,
        debtor_account_number="SG-D-01",
        debtor_name="Alice Tan",
        creditor_account_number="SG-C-01",
        creditor_name="Bob Lee",
    )

    root = etree.fromstring(xml_bytes)
    assert root.find(".//ns:CdtTrfTxInf/ns:PmtId/ns:EndToEndId", _NSMAP).text == str(payment.id)


@pytest.mark.parametrize(
    "status",
    [s for s in PaymentStatus if s is not PaymentStatus.SETTLED],
)
def test_build_pacs008_rejects_non_settled_payments(status: PaymentStatus) -> None:
    payment = _settled_payment(status=status)

    with pytest.raises(Pacs008EmissionError, match="settled"):
        build_pacs008(
            payment,
            debtor_account_number="SG-D-01",
            debtor_name="Alice Tan",
            creditor_account_number="SG-C-01",
            creditor_name="Bob Lee",
        )
