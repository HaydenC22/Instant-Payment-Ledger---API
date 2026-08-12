from uuid import uuid4

from app.domain.webhooks.services import enqueue_payment_webhook_event

from .fakes import FakeWebhookState, FakeWebhooksUnitOfWork


async def test_enqueues_a_delivery_for_a_matching_subscription() -> None:
    state = FakeWebhookState()
    state.seed_subscription(event_types=("payment.settled",))
    payment_id = uuid4()

    async with FakeWebhooksUnitOfWork(state) as uow:
        await enqueue_payment_webhook_event(
            uow,
            payment_id=payment_id,
            event_type="payment.settled",
            payload={"id": str(payment_id)},
        )

    assert len(state.deliveries) == 1
    delivery = next(iter(state.deliveries.values()))
    assert delivery.event_type == "payment.settled"
    assert delivery.payment_id == payment_id


async def test_skips_a_subscription_that_does_not_list_the_event_type() -> None:
    state = FakeWebhookState()
    state.seed_subscription(event_types=("payment.failed",))

    async with FakeWebhooksUnitOfWork(state) as uow:
        await enqueue_payment_webhook_event(
            uow, payment_id=uuid4(), event_type="payment.settled", payload={}
        )

    assert len(state.deliveries) == 0


async def test_subscription_with_no_event_types_receives_every_event() -> None:
    state = FakeWebhookState()
    state.seed_subscription(event_types=())

    async with FakeWebhooksUnitOfWork(state) as uow:
        await enqueue_payment_webhook_event(
            uow, payment_id=uuid4(), event_type="payment.settled", payload={}
        )

    assert len(state.deliveries) == 1


async def test_inactive_subscriptions_are_skipped() -> None:
    state = FakeWebhookState()
    state.seed_subscription(active=False)

    async with FakeWebhooksUnitOfWork(state) as uow:
        await enqueue_payment_webhook_event(
            uow, payment_id=uuid4(), event_type="payment.settled", payload={}
        )

    assert len(state.deliveries) == 0


async def test_enqueues_one_delivery_per_matching_subscription() -> None:
    state = FakeWebhookState()
    state.seed_subscription(event_types=())
    state.seed_subscription(event_types=("payment.settled",))
    state.seed_subscription(event_types=("payment.failed",))  # should not match

    async with FakeWebhooksUnitOfWork(state) as uow:
        await enqueue_payment_webhook_event(
            uow, payment_id=uuid4(), event_type="payment.settled", payload={}
        )

    assert len(state.deliveries) == 2
