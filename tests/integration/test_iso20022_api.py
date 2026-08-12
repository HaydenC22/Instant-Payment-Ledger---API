import uuid
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from lxml import etree

from app.api.deps import get_db_session, get_uow_factory
from app.infra.db.unit_of_work import make_uow_factory
from app.infra.iso20022.pacs008 import PACS008_NAMESPACE
from app.main import app

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
_NSMAP = {"ns": PACS008_NAMESPACE}


@pytest.fixture
async def client(db_sessionmaker):
    async def override_get_db_session():
        async with db_sessionmaker() as session:
            yield session

    def override_get_uow_factory():
        return make_uow_factory(db_sessionmaker)

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_uow_factory] = override_get_uow_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create_account(client, account_number: str, owner_name: str) -> str:
    response = await client.post(
        "/accounts",
        json={
            "account_number": account_number,
            "owner_name": owner_name,
            "account_type": "customer",
            "currency": "SGD",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_payment_via_json(client, *, debtor_id: str, creditor_id: str, amount="10.00"):
    return await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": amount,
            "currency": "SGD",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


async def test_ingest_pain001_creates_a_payment(client) -> None:
    await _create_account(client, "SG-D-0001", "Alice Tan")
    await _create_account(client, "SG-C-0001", "Bob Lee")
    xml_body = (FIXTURES_DIR / "pain001_valid.xml").read_bytes()

    response = await client.post(
        "/iso20022/pain001", content=xml_body, headers={"Content-Type": "application/xml"}
    )

    assert response.status_code == 201
    payment = response.json()
    assert payment["amount"] == "20.00"
    assert payment["currency"] == "SGD"
    assert payment["status"] == "initiated"
    assert payment["end_to_end_id"] == "E2E-0001"


async def test_ingest_malformed_pain001_returns_400(client) -> None:
    xml_body = (FIXTURES_DIR / "pain001_malformed.xml").read_bytes()

    response = await client.post(
        "/iso20022/pain001", content=xml_body, headers={"Content-Type": "application/xml"}
    )

    assert response.status_code == 400


async def test_ingest_pain001_with_unknown_account_returns_404(client) -> None:
    xml_body = (FIXTURES_DIR / "pain001_valid.xml").read_bytes()

    response = await client.post(
        "/iso20022/pain001", content=xml_body, headers={"Content-Type": "application/xml"}
    )

    assert response.status_code == 404


async def test_pacs008_round_trips_a_settled_payment(client) -> None:
    debtor_id = await _create_account(client, "SG-D-0002", "Carol Ng")
    creditor_id = await _create_account(client, "SG-C-0002", "Dan Ong")
    create = await _create_payment_via_json(
        client, debtor_id=debtor_id, creditor_id=creditor_id, amount="15.00"
    )
    payment_id = create.json()["id"]
    await client.post(f"/payments/{payment_id}/authorise")
    await client.post(f"/payments/{payment_id}/settle")

    response = await client.get(f"/iso20022/{payment_id}/pacs008")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    root = etree.fromstring(response.content)
    assert root.find(".//ns:CdtTrfTxInf/ns:PmtId/ns:TxId", _NSMAP).text == payment_id
    amt_el = root.find(".//ns:CdtTrfTxInf/ns:IntrBkSttlmAmt", _NSMAP)
    assert amt_el.text == "15.00"
    assert amt_el.get("Ccy") == "SGD"
    assert (
        root.find(".//ns:CdtTrfTxInf/ns:DbtrAcct/ns:Id/ns:Othr/ns:Id", _NSMAP).text == "SG-D-0002"
    )
    assert (
        root.find(".//ns:CdtTrfTxInf/ns:CdtrAcct/ns:Id/ns:Othr/ns:Id", _NSMAP).text == "SG-C-0002"
    )


async def test_pacs008_for_unsettled_payment_returns_409(client) -> None:
    debtor_id = await _create_account(client, "SG-D-0003", "Eve Koh")
    creditor_id = await _create_account(client, "SG-C-0003", "Faz Lim")
    create = await _create_payment_via_json(client, debtor_id=debtor_id, creditor_id=creditor_id)
    payment_id = create.json()["id"]

    response = await client.get(f"/iso20022/{payment_id}/pacs008")

    assert response.status_code == 409


async def test_pacs008_for_unknown_payment_returns_404(client) -> None:
    response = await client.get(f"/iso20022/{uuid4()}/pacs008")
    assert response.status_code == 404
