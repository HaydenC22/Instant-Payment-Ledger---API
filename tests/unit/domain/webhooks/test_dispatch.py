import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.webhooks.dispatch import (
    dispatch_due_deliveries,
    dispatch_one_delivery,
    sign_payload,
)
from app.domain.webhooks.entities import DeliveryStatus

from .fakes import FakeWebhookSender, FakeWebhookState, make_uow_factory


async def test_successful_delivery_is_marked_delivered_and_signed_correctly() -> None:
    state = FakeWebhookState()
    sub = state.seed_subscription(secret="topsecret")
    delivery = state.seed_delivery(subscription_id=sub.id, payload={"a": 1})
    sender = FakeWebhookSender(status_code=200)

    await dispatch_one_delivery(make_uow_factory(state), sender, delivery, sub)

    assert state.deliveries[delivery.id].status is DeliveryStatus.DELIVERED
    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["url"] == sub.url
    expected_body = json.dumps({"a": 1}, default=str, sort_keys=True).encode()
    assert call["body"] == expected_body
    assert call["headers"]["X-Webhook-Signature"] == sign_payload("topsecret", expected_body)


async def test_failed_delivery_schedules_a_retry_with_backoff() -> None:
    state = FakeWebhookState()
    sub = state.seed_subscription()
    delivery = state.seed_delivery(subscription_id=sub.id, attempt_count=0)
    sender = FakeWebhookSender(fail_times=1)  # always fails in this test (1 call made)

    before = datetime.now(UTC)
    await dispatch_one_delivery(make_uow_factory(state), sender, delivery, sub, max_attempts=5)

    updated = state.deliveries[delivery.id]
    assert updated.status is DeliveryStatus.PENDING
    assert updated.attempt_count == 1
    assert updated.last_error == "HTTP 500"
    assert updated.next_attempt_at > before + timedelta(seconds=1)


async def test_network_exception_is_treated_as_a_failed_attempt() -> None:
    state = FakeWebhookState()
    sub = state.seed_subscription()
    delivery = state.seed_delivery(subscription_id=sub.id)
    sender = FakeWebhookSender(fail_times=1, raise_exception=True)

    await dispatch_one_delivery(make_uow_factory(state), sender, delivery, sub, max_attempts=5)

    updated = state.deliveries[delivery.id]
    assert updated.status is DeliveryStatus.PENDING
    assert "ConnectionError" in updated.last_error


async def test_exceeding_max_attempts_moves_to_dead_letter() -> None:
    state = FakeWebhookState()
    sub = state.seed_subscription()
    delivery = state.seed_delivery(subscription_id=sub.id, attempt_count=4)  # about to be 5th
    sender = FakeWebhookSender(fail_times=1)

    await dispatch_one_delivery(make_uow_factory(state), sender, delivery, sub, max_attempts=5)

    updated = state.deliveries[delivery.id]
    assert updated.status is DeliveryStatus.DEAD_LETTER
    assert updated.attempt_count == 5


async def test_delivery_eventually_succeeds_after_transient_failures_across_cycles() -> None:
    """Mirrors the worker's real loop: dispatch_one_delivery is called again each cycle
    with the same (now-updated) delivery, until it succeeds or dead-letters.
    """
    state = FakeWebhookState()
    sub = state.seed_subscription()
    delivery = state.seed_delivery(subscription_id=sub.id)
    sender = FakeWebhookSender(fail_times=2)  # fails twice, succeeds on the 3rd call
    uow_factory = make_uow_factory(state)

    for _ in range(3):
        current = state.deliveries[delivery.id]
        if current.status is not DeliveryStatus.PENDING:
            break
        await dispatch_one_delivery(uow_factory, sender, current, sub, max_attempts=10)

    assert state.deliveries[delivery.id].status is DeliveryStatus.DELIVERED
    assert len(sender.calls) == 3


async def test_dispatch_due_deliveries_skips_deliveries_whose_next_attempt_is_in_the_future() -> (
    None
):
    state = FakeWebhookState()
    sub = state.seed_subscription()
    state.seed_delivery(
        subscription_id=sub.id, next_attempt_at=datetime.now(UTC) + timedelta(hours=1)
    )
    sender = FakeWebhookSender(status_code=200)

    processed = await dispatch_due_deliveries(make_uow_factory(state), sender)

    assert processed == 0
    assert len(sender.calls) == 0


async def test_dispatch_due_deliveries_processes_everything_that_is_due() -> None:
    state = FakeWebhookState()
    sub = state.seed_subscription()
    state.seed_delivery(subscription_id=sub.id)
    state.seed_delivery(subscription_id=sub.id)
    sender = FakeWebhookSender(status_code=200)

    processed = await dispatch_due_deliveries(make_uow_factory(state), sender)

    assert processed == 2
    assert all(d.status is DeliveryStatus.DELIVERED for d in state.deliveries.values())


async def test_dispatch_due_deliveries_skips_deliveries_for_a_missing_subscription() -> None:
    state = FakeWebhookState()
    state.seed_delivery(subscription_id=uuid4())  # no matching subscription seeded
    sender = FakeWebhookSender(status_code=200)

    processed = await dispatch_due_deliveries(make_uow_factory(state), sender)

    assert processed == 1  # counted as "seen this cycle" even though it couldn't be sent
    assert len(sender.calls) == 0
