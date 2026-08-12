import uuid
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session, get_uow_factory
from app.infra.db.unit_of_work import make_uow_factory
from app.main import app


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


async def _create_account(client, account_number: str) -> str:
    response = await client.post(
        "/accounts",
        json={
            "account_number": account_number,
            "owner_name": "Test Owner",
            "account_type": "customer",
            "currency": "SGD",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_payment(client, *, debtor_id: str, creditor_id: str, amount: str = "5.00"):
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


async def test_full_payment_lifecycle_via_api(client) -> None:
    debtor_id = await _create_account(client, "API-D-1")
    creditor_id = await _create_account(client, "API-C-1")

    create = await _create_payment(
        client, debtor_id=debtor_id, creditor_id=creditor_id, amount="20.00"
    )
    assert create.status_code == 201
    payment = create.json()
    assert payment["status"] == "initiated"
    payment_id = payment["id"]

    authorise = await client.post(f"/payments/{payment_id}/authorise")
    assert authorise.status_code == 200
    assert authorise.json()["status"] == "authorised"

    settle = await client.post(f"/payments/{payment_id}/settle")
    assert settle.status_code == 200
    assert settle.json()["status"] == "settled"

    get_response = await client.get(f"/payments/{payment_id}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "settled"

    debtor_balance = await client.get(f"/accounts/{debtor_id}/balance", params={"currency": "SGD"})
    creditor_balance = await client.get(
        f"/accounts/{creditor_id}/balance", params={"currency": "SGD"}
    )
    assert debtor_balance.json()["balance"] == "-20.00"
    assert creditor_balance.json()["balance"] == "20.00"


async def test_settling_before_authorising_returns_409(client) -> None:
    debtor_id = await _create_account(client, "API-D-2")
    creditor_id = await _create_account(client, "API-C-2")
    create = await _create_payment(client, debtor_id=debtor_id, creditor_id=creditor_id)
    payment_id = create.json()["id"]

    response = await client.post(f"/payments/{payment_id}/settle")
    assert response.status_code == 409


async def test_create_payment_with_unknown_account_returns_404(client) -> None:
    response = await _create_payment(client, debtor_id=str(uuid4()), creditor_id=str(uuid4()))
    assert response.status_code == 404


async def test_create_payment_with_same_debtor_and_creditor_returns_422(client) -> None:
    account_id = await _create_account(client, "API-D-3")
    response = await _create_payment(client, debtor_id=account_id, creditor_id=account_id)
    assert response.status_code == 422


async def test_get_unknown_payment_returns_404(client) -> None:
    response = await client.get(f"/payments/{uuid4()}")
    assert response.status_code == 404


async def test_fail_payment_records_reason(client) -> None:
    debtor_id = await _create_account(client, "API-D-4")
    creditor_id = await _create_account(client, "API-C-4")
    create = await _create_payment(client, debtor_id=debtor_id, creditor_id=creditor_id)
    payment_id = create.json()["id"]

    response = await client.post(f"/payments/{payment_id}/fail", json={"reason": "risk decline"})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
