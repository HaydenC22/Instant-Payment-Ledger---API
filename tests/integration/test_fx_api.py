import uuid

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


async def _create_account(client, account_number: str, currency: str) -> str:
    response = await client.post(
        "/accounts",
        json={
            "account_number": account_number,
            "owner_name": "Test Owner",
            "account_type": "customer",
            "currency": currency,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_cross_currency_settlement_credits_the_creditor_in_their_own_currency(
    client,
) -> None:
    debtor_id = await _create_account(client, "FX-D-1", "SGD")
    creditor_id = await _create_account(client, "FX-C-1", "USD")

    create = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": "100.00",
            "currency": "SGD",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert create.status_code == 201
    payment_id = create.json()["id"]

    await client.post(f"/payments/{payment_id}/authorise")
    settle = await client.post(f"/payments/{payment_id}/settle")
    assert settle.status_code == 200
    body = settle.json()
    assert body["fx_rate_id"] is not None
    assert body["creditor_amount"] == "74.00"  # seeded SGD->USD mock rate is 0.74

    debtor_balance = await client.get(f"/accounts/{debtor_id}/balance", params={"currency": "SGD"})
    creditor_balance = await client.get(
        f"/accounts/{creditor_id}/balance", params={"currency": "USD"}
    )
    assert debtor_balance.json()["balance"] == "-100.00"
    assert creditor_balance.json()["balance"] == "74.00"


async def test_reversing_a_cross_currency_payment_zeroes_out_both_balances(client) -> None:
    debtor_id = await _create_account(client, "FX-D-2", "SGD")
    creditor_id = await _create_account(client, "FX-C-2", "USD")

    create = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": "50.00",
            "currency": "SGD",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    payment_id = create.json()["id"]
    await client.post(f"/payments/{payment_id}/authorise")
    await client.post(f"/payments/{payment_id}/settle")

    reverse = await client.post(f"/payments/{payment_id}/reverse")
    assert reverse.status_code == 200
    assert reverse.json()["status"] == "reversed"

    debtor_balance = await client.get(f"/accounts/{debtor_id}/balance", params={"currency": "SGD"})
    creditor_balance = await client.get(
        f"/accounts/{creditor_id}/balance", params={"currency": "USD"}
    )
    assert debtor_balance.json()["balance"] == "0.00"
    assert creditor_balance.json()["balance"] == "0.00"


async def test_initiating_a_payment_with_currency_not_matching_debtor_account_returns_422(
    client,
) -> None:
    debtor_id = await _create_account(client, "FX-D-3", "SGD")
    creditor_id = await _create_account(client, "FX-C-3", "USD")

    response = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": "10.00",
            "currency": "USD",  # debtor account is SGD
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 422


async def test_settlement_with_no_configured_rate_returns_409(client) -> None:
    debtor_id = await _create_account(client, "FX-D-4", "SGD")
    creditor_id = await _create_account(client, "FX-C-4", "JPY")  # no SGD->JPY mock rate seeded

    create = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": "10.00",
            "currency": "SGD",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    payment_id = create.json()["id"]
    await client.post(f"/payments/{payment_id}/authorise")

    response = await client.post(f"/payments/{payment_id}/settle")
    assert response.status_code == 409
