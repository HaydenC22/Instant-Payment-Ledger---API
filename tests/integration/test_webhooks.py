import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session, get_uow_factory
from app.domain.webhooks.dispatch import (
    dispatch_due_deliveries,
    dispatch_one_delivery,
    sign_payload,
)
from app.infra.db.models import WebhookDeliveryModel
from app.infra.db.repositories.webhook_repository import (
    SqlAlchemyWebhookRepository,
    _to_domain_delivery,
)
from app.infra.db.unit_of_work import make_uow_factory
from app.infra.webhooks.http_sender import HttpxWebhookSender
from app.main import app


class _RecordingReceiver:
    """A throwaway ASGI 'subscriber' app: fails the first `fail_times` calls, then 200s."""

    def __init__(self, *, fail_times: int = 0):
        self.calls: list[dict] = []
        self.fail_times = fail_times

    async def __call__(self, scope, receive, send) -> None:
        assert scope["type"] == "http"
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        headers = {k.decode(): v.decode() for k, v in scope["headers"]}
        self.calls.append({"body": body, "headers": headers})
        status = 500 if len(self.calls) <= self.fail_times else 200
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})


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


async def _create_payment(client, *, debtor_id: str, creditor_id: str, amount="10.00") -> str:
    response = await client.post(
        "/payments",
        json={
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": amount,
            "currency": "SGD",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_subscription_creation_never_echoes_the_secret(client) -> None:
    response = await client.post(
        "/webhooks/subscriptions",
        json={"url": "https://example.test/hook", "secret": "supersecretvalue", "event_types": []},
    )
    assert response.status_code == 201
    body = response.json()
    assert "secret" not in body
    assert body["url"] == "https://example.test/hook"


async def test_settling_a_payment_enqueues_a_delivery_that_dispatch_delivers(
    client, db_sessionmaker
) -> None:
    debtor_id = await _create_account(client, "WH-D-1")
    creditor_id = await _create_account(client, "WH-C-1")

    sub_response = await client.post(
        "/webhooks/subscriptions",
        json={"url": "http://stub/webhook", "secret": "topsecretvalue", "event_types": []},
    )
    subscription_id = sub_response.json()["id"]

    payment_id = await _create_payment(client, debtor_id=debtor_id, creditor_id=creditor_id)
    await client.post(f"/payments/{payment_id}/authorise")
    await client.post(f"/payments/{payment_id}/settle")

    receiver = _RecordingReceiver()
    uow_factory = make_uow_factory(db_sessionmaker)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=receiver), base_url="http://stub"
    ) as http_client:
        sender = HttpxWebhookSender(http_client)
        processed = await dispatch_due_deliveries(uow_factory, sender)

    # initiated, authorised, and settled each enqueue their own delivery for this subscription.
    assert processed == 3
    assert len(receiver.calls) == 3
    settled_call = next(c for c in receiver.calls if json.loads(c["body"])["status"] == "settled")
    assert settled_call["headers"]["x-webhook-event"] == "payment.settled"
    assert settled_call["headers"]["x-webhook-signature"] == sign_payload(
        "topsecretvalue", settled_call["body"]
    )

    async with db_sessionmaker() as session:
        repo = SqlAlchemyWebhookRepository(session)
        dead_letters = await repo.list_dead_letters()
    assert dead_letters == []
    assert subscription_id  # sanity: subscription really was the one used


async def _fetch_delivery(db_sessionmaker, delivery_id):
    async with db_sessionmaker() as session:
        row = await session.get(WebhookDeliveryModel, delivery_id)
        assert row is not None
        return _to_domain_delivery(row)


async def test_delivery_that_always_fails_eventually_becomes_a_browsable_dead_letter(
    client, db_sessionmaker
) -> None:
    debtor_id = await _create_account(client, "WH-D-2")
    creditor_id = await _create_account(client, "WH-C-2")
    await client.post(
        "/webhooks/subscriptions",
        json={"url": "http://stub/webhook", "secret": "anothersecret123", "event_types": []},
    )
    await _create_payment(client, debtor_id=debtor_id, creditor_id=creditor_id)

    uow_factory = make_uow_factory(db_sessionmaker)
    async with uow_factory() as uow:
        due = await uow.webhooks.list_due_deliveries(now=datetime.now(UTC), limit=10)
        subscriptions = {s.id: s for s in await uow.webhooks.list_active_subscriptions()}
    delivery = due[0]
    subscription = subscriptions[delivery.subscription_id]

    receiver = _RecordingReceiver(fail_times=999)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=receiver), base_url="http://stub"
    ) as http_client:
        sender = HttpxWebhookSender(http_client)
        # Re-fetch between attempts (regardless of next_attempt_at) rather than waiting out
        # the real backoff delay — dispatch_one_delivery itself doesn't check due-ness.
        for _ in range(3):
            current = await _fetch_delivery(db_sessionmaker, delivery.id)
            await dispatch_one_delivery(uow_factory, sender, current, subscription, max_attempts=3)

    async with db_sessionmaker() as session:
        repo = SqlAlchemyWebhookRepository(session)
        dead_letters = await repo.list_dead_letters()
    assert len(dead_letters) == 1
    assert dead_letters[0].attempt_count == 3

    response = await client.get("/webhooks/dead-letters")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["attempt_count"] == 3
    assert body[0]["last_error"] == "HTTP 500"
