import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session
from app.infra.qr.sgqr import parse_tlv, verify_crc
from app.main import app

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


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


async def _create_account(client, account_number: str) -> str:
    response = await client.post(
        "/accounts",
        json={
            "account_number": account_number,
            "owner_name": "Alice Tan",
            "account_type": "customer",
            "currency": "SGD",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_generate_qr_returns_a_valid_png_with_payload_header(client) -> None:
    account_id = await _create_account(client, "QR-0001")

    response = await client.post("/qr/generate", json={"account_id": account_id, "amount": "15.00"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(_PNG_MAGIC)

    payload = response.headers["x-sgqr-payload"]
    assert verify_crc(payload)
    fields = parse_tlv(payload)
    assert fields["54"] == "15.00"
    merchant_fields = parse_tlv(fields["26"])
    assert merchant_fields["01"] == "QR-0001"


async def test_generate_static_qr_without_amount(client) -> None:
    account_id = await _create_account(client, "QR-0002")

    response = await client.post("/qr/generate", json={"account_id": account_id})

    assert response.status_code == 200
    payload = response.headers["x-sgqr-payload"]
    assert parse_tlv(payload)["01"] == "11"  # static QR point-of-initiation


async def test_generate_qr_for_unknown_account_returns_404(client) -> None:
    response = await client.post("/qr/generate", json={"account_id": str(uuid.uuid4())})
    assert response.status_code == 404
