from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session
from app.main import app


@pytest.fixture
async def client(db_sessionmaker):
    async def override_get_db_session():
        async with db_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_create_account_returns_201(client) -> None:
    response = await client.post(
        "/accounts",
        json={
            "account_number": "SG-0001",
            "owner_name": "Alice Tan",
            "account_type": "customer",
            "currency": "sgd",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["currency"] == "SGD"
    assert body["version"] == 0
    assert body["status"] == "active"


async def test_create_account_with_duplicate_number_returns_409(client) -> None:
    payload = {
        "account_number": "SG-0002",
        "owner_name": "Bob Lee",
        "account_type": "customer",
        "currency": "SGD",
    }
    first = await client.post("/accounts", json=payload)
    assert first.status_code == 201

    second = await client.post("/accounts", json=payload)
    assert second.status_code == 409


async def test_get_unknown_account_returns_404(client) -> None:
    response = await client.get(f"/accounts/{uuid4()}")
    assert response.status_code == 404


async def test_get_balance_for_fresh_account_is_zero(client) -> None:
    create = await client.post(
        "/accounts",
        json={
            "account_number": "SG-0003",
            "owner_name": "Carol Ng",
            "account_type": "customer",
            "currency": "SGD",
        },
    )
    account_id = create.json()["id"]

    response = await client.get(f"/accounts/{account_id}/balance", params={"currency": "SGD"})

    assert response.status_code == 200
    assert response.json()["balance"] == "0"


async def test_get_balance_for_unknown_account_returns_404(client) -> None:
    response = await client.get(f"/accounts/{uuid4()}/balance", params={"currency": "SGD"})
    assert response.status_code == 404
