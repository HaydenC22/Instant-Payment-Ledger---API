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


async def _settle_payment(
    client, *, debtor_id: str, creditor_id: str, amount: str, e2e_id: str
) -> str:
    create = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": amount,
            "currency": "SGD",
            "end_to_end_id": e2e_id,
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert create.status_code == 201
    payment_id = create.json()["id"]
    await client.post(f"/payments/{payment_id}/authorise")
    settle = await client.post(f"/payments/{payment_id}/settle")
    assert settle.status_code == 200
    return payment_id


async def test_reconciliation_run_matches_a_correct_settlement_file(client) -> None:
    debtor_id = await _create_account(client, "REC-D-1")
    creditor_id = await _create_account(client, "REC-C-1")
    await _settle_payment(
        client, debtor_id=debtor_id, creditor_id=creditor_id, amount="30.00", e2e_id="REC-E2E-1"
    )

    csv_body = (
        "external_ref,amount,currency,settled_at\n"
        "REC-E2E-1,30.00,SGD,2026-08-12T00:00:00+00:00\n"
    )
    response = await client.post(
        "/reconciliation/run",
        content=csv_body,
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["matched_count"] == 1
    assert body["break_count"] == 0
    assert body["breaks"] == []


async def test_reconciliation_run_reports_an_amount_mismatch_break(client) -> None:
    debtor_id = await _create_account(client, "REC-D-2")
    creditor_id = await _create_account(client, "REC-C-2")
    payment_id = await _settle_payment(
        client, debtor_id=debtor_id, creditor_id=creditor_id, amount="30.00", e2e_id="REC-E2E-2"
    )

    csv_body = (
        "external_ref,amount,currency,settled_at\n"
        "REC-E2E-2,29.00,SGD,2026-08-12T00:00:00+00:00\n"
    )
    response = await client.post(
        "/reconciliation/run",
        content=csv_body,
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["matched_count"] == 0
    assert body["break_count"] == 1
    assert body["breaks"][0]["break_type"] == "amount_mismatch"
    assert body["breaks"][0]["payment_id"] == payment_id


async def test_reconciliation_run_reports_missing_in_ledger(client) -> None:
    csv_body = (
        "external_ref,amount,currency,settled_at\n"
        "GHOST-REF,10.00,SGD,2026-08-12T00:00:00+00:00\n"
    )
    response = await client.post(
        "/reconciliation/run",
        content=csv_body,
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["break_count"] == 1
    assert body["breaks"][0]["break_type"] == "missing_in_ledger"


async def test_malformed_csv_returns_400(client) -> None:
    response = await client.post(
        "/reconciliation/run", content="not,a,valid,csv\n", headers={"Content-Type": "text/csv"}
    )
    assert response.status_code == 400


async def test_get_reconciliation_run_returns_the_persisted_result(client) -> None:
    csv_body = (
        "external_ref,amount,currency,settled_at\n" "SOLO-REF,5.00,SGD,2026-08-12T00:00:00+00:00\n"
    )
    create = await client.post(
        "/reconciliation/run", content=csv_body, headers={"Content-Type": "text/csv"}
    )
    run_id = create.json()["id"]

    response = await client.get(f"/reconciliation/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == run_id
    assert body["break_count"] == 1


async def test_get_unknown_reconciliation_run_returns_404(client) -> None:
    response = await client.get(f"/reconciliation/runs/{uuid4()}")
    assert response.status_code == 404
