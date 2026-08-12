import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_db_session, get_uow_factory
from app.infra.db.models import PaymentModel
from app.infra.db.unit_of_work import make_uow_factory
from app.main import app

CONCURRENCY_RUNS = 3  # repeat the race to catch flakiness, per the project's testing strategy


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


async def _count_payments(db_sessionmaker) -> int:
    async with db_sessionmaker() as session:
        result = await session.execute(select(PaymentModel))
        return len(result.scalars().all())


async def test_missing_idempotency_key_header_is_rejected(client) -> None:
    debtor_id = await _create_account(client, "IDEM-D-0")
    creditor_id = await _create_account(client, "IDEM-C-0")

    response = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": "5.00",
            "currency": "SGD",
        },
    )
    assert response.status_code == 422


async def test_same_key_replays_the_original_response(client, db_sessionmaker) -> None:
    debtor_id = await _create_account(client, "IDEM-D-1")
    creditor_id = await _create_account(client, "IDEM-C-1")
    body = {
        "debtor_account_id": debtor_id,
        "creditor_account_id": creditor_id,
        "amount": "20.00",
        "currency": "SGD",
    }
    key = str(uuid.uuid4())

    first = await client.post("/payments", json=body, headers={"Idempotency-Key": key})
    second = await client.post("/payments", json=body, headers={"Idempotency-Key": key})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert await _count_payments(db_sessionmaker) == 1


async def test_same_key_with_a_different_body_returns_422(client) -> None:
    debtor_id = await _create_account(client, "IDEM-D-2")
    creditor_id = await _create_account(client, "IDEM-C-2")
    key = str(uuid.uuid4())

    first = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": "20.00",
            "currency": "SGD",
        },
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201

    second = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": "99.00",
            "currency": "SGD",
        },
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 422


@pytest.mark.parametrize("run", range(CONCURRENCY_RUNS))
async def test_n_concurrent_identical_requests_create_exactly_one_payment(
    client, db_sessionmaker, run: int
) -> None:
    """The idempotency proof: N clients racing the same key must not create N payments.

    Some concurrent callers may see a fast 409 "already in progress" instead of a 201,
    depending on exactly how the race lands (see initiate_payment_idempotent's docstring)
    — that's a legitimate outcome. What must never happen is a second *payment* appearing.
    """
    debtor_id = await _create_account(client, f"IDEM-D-3-{run}")
    creditor_id = await _create_account(client, f"IDEM-C-3-{run}")
    body = {
        "debtor_account_id": debtor_id,
        "creditor_account_id": creditor_id,
        "amount": "7.00",
        "currency": "SGD",
    }
    key = str(uuid.uuid4())
    concurrent_requests = 20

    responses = await asyncio.gather(
        *(
            client.post("/payments", json=body, headers={"Idempotency-Key": key})
            for _ in range(concurrent_requests)
        )
    )

    statuses = [r.status_code for r in responses]
    assert all(status in (201, 409) for status in statuses)
    assert statuses.count(201) >= 1

    payment_ids = {r.json()["id"] for r in responses if r.status_code == 201}
    assert len(payment_ids) == 1, "every successful response must reference the same payment"
    assert await _count_payments(db_sessionmaker) == 1

    # A follow-up call once the race has settled must replay the completed response.
    followup = await client.post("/payments", json=body, headers={"Idempotency-Key": key})
    assert followup.status_code == 201
    assert followup.json()["id"] in payment_ids
    assert await _count_payments(db_sessionmaker) == 1
