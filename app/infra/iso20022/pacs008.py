from datetime import UTC, datetime
from uuid import uuid4

from lxml import etree

from app.domain.payments.entities import Payment, PaymentStatus

PACS008_NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"


class Pacs008EmissionError(ValueError):
    pass


def build_pacs008(
    payment: Payment,
    *,
    debtor_account_number: str,
    debtor_name: str,
    creditor_account_number: str,
    creditor_name: str,
) -> bytes:
    """Emits a pacs.008.001.08 FIToFICustomerCreditTransfer message for a settled payment.

    Deliberately partial, matching this project's ISO 20022 scope: covers the fields
    needed to represent one domestic credit transfer settlement, not the full FI-to-FI
    agent chain, charges, or regulatory reporting blocks a production implementation
    would carry.
    """
    if payment.status is not PaymentStatus.SETTLED:
        raise Pacs008EmissionError(
            f"pacs.008 can only be emitted for a settled payment, got status={payment.status}"
        )

    document = etree.Element("Document", nsmap={None: PACS008_NAMESPACE})
    fi_to_fi = etree.SubElement(document, "FIToFICstmrCdtTrf")

    grp_hdr = etree.SubElement(fi_to_fi, "GrpHdr")
    etree.SubElement(grp_hdr, "MsgId").text = str(uuid4())
    etree.SubElement(grp_hdr, "CreDtTm").text = datetime.now(UTC).isoformat(timespec="seconds")
    etree.SubElement(grp_hdr, "NbOfTxs").text = "1"
    sttlm_inf = etree.SubElement(grp_hdr, "SttlmInf")
    etree.SubElement(sttlm_inf, "SttlmMtd").text = "CLRG"

    tx_inf = etree.SubElement(fi_to_fi, "CdtTrfTxInf")
    pmt_id = etree.SubElement(tx_inf, "PmtId")
    etree.SubElement(pmt_id, "EndToEndId").text = payment.end_to_end_id or str(payment.id)
    etree.SubElement(pmt_id, "TxId").text = str(payment.id)

    etree.SubElement(tx_inf, "IntrBkSttlmAmt", Ccy=payment.currency).text = str(payment.amount)
    etree.SubElement(tx_inf, "ChrgBr").text = "SLEV"

    dbtr = etree.SubElement(tx_inf, "Dbtr")
    etree.SubElement(dbtr, "Nm").text = debtor_name
    dbtr_acct_othr = etree.SubElement(
        etree.SubElement(etree.SubElement(tx_inf, "DbtrAcct"), "Id"), "Othr"
    )
    etree.SubElement(dbtr_acct_othr, "Id").text = debtor_account_number

    cdtr = etree.SubElement(tx_inf, "Cdtr")
    etree.SubElement(cdtr, "Nm").text = creditor_name
    cdtr_acct_othr = etree.SubElement(
        etree.SubElement(etree.SubElement(tx_inf, "CdtrAcct"), "Id"), "Othr"
    )
    etree.SubElement(cdtr_acct_othr, "Id").text = creditor_account_number

    return etree.tostring(document, xml_declaration=True, encoding="UTF-8", pretty_print=True)
