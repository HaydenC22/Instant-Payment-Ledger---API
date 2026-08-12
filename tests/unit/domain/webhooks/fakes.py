from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.domain.webhooks.entities import DeliveryStatus, WebhookDelivery, WebhookSubscription


@dataclass
class FakeWebhookState:
    subscriptions: dict[UUID, WebhookSubscription] = field(default_factory=dict)
    deliveries: dict[UUID, WebhookDelivery] = field(default_factory=dict)

    def seed_subscription(self, **overrides) -> WebhookSubscription:
        defaults = dict(
            id=uuid4(),
            url="https://example.test/hook",
            secret="s3cr3t",
            event_types=(),
            active=True,
        )
        sub = WebhookSubscription(**{**defaults, **overrides})
        self.subscriptions[sub.id] = sub
        return sub

    def seed_delivery(self, **overrides) -> WebhookDelivery:
        defaults = dict(
            id=uuid4(),
            subscription_id=uuid4(),
            payment_id=uuid4(),
            event_type="payment.settled",
            payload={"foo": "bar"},
            status=DeliveryStatus.PENDING,
            attempt_count=0,
            next_attempt_at=datetime.now(UTC),
            last_error=None,
        )
        delivery = WebhookDelivery(**{**defaults, **overrides})
        self.deliveries[delivery.id] = delivery
        return delivery


class FakeWebhookRepository:
    def __init__(self, state: FakeWebhookState):
        self._state = state

    async def create_subscription(
        self, *, url: str, secret: str, event_types: list[str]
    ) -> WebhookSubscription:
        sub = WebhookSubscription(
            id=uuid4(), url=url, secret=secret, event_types=tuple(event_types), active=True
        )
        self._state.subscriptions[sub.id] = sub
        return sub

    async def list_active_subscriptions(self) -> list[WebhookSubscription]:
        return [s for s in self._state.subscriptions.values() if s.active]

    async def enqueue_delivery(
        self, *, subscription_id: UUID, payment_id, event_type: str, payload: dict[str, Any]
    ) -> UUID:
        delivery = WebhookDelivery(
            id=uuid4(),
            subscription_id=subscription_id,
            payment_id=payment_id,
            event_type=event_type,
            payload=payload,
            status=DeliveryStatus.PENDING,
            attempt_count=0,
            next_attempt_at=datetime.now(UTC),
            last_error=None,
        )
        self._state.deliveries[delivery.id] = delivery
        return delivery.id

    async def list_due_deliveries(self, *, now: datetime, limit: int) -> list[WebhookDelivery]:
        due = [
            d
            for d in self._state.deliveries.values()
            if d.status is DeliveryStatus.PENDING and d.next_attempt_at <= now
        ]
        due.sort(key=lambda d: d.next_attempt_at)
        return due[:limit]

    async def mark_delivered(self, delivery_id: UUID) -> None:
        d = self._state.deliveries[delivery_id]
        self._state.deliveries[delivery_id] = replace(d, status=DeliveryStatus.DELIVERED)

    async def mark_retry(
        self, delivery_id: UUID, *, attempt_count: int, next_attempt_at: datetime, last_error: str
    ) -> None:
        d = self._state.deliveries[delivery_id]
        self._state.deliveries[delivery_id] = replace(
            d, attempt_count=attempt_count, next_attempt_at=next_attempt_at, last_error=last_error
        )

    async def mark_dead_letter(
        self, delivery_id: UUID, *, attempt_count: int, last_error: str
    ) -> None:
        d = self._state.deliveries[delivery_id]
        self._state.deliveries[delivery_id] = replace(
            d,
            status=DeliveryStatus.DEAD_LETTER,
            attempt_count=attempt_count,
            last_error=last_error,
        )

    async def list_dead_letters(self) -> list[WebhookDelivery]:
        return [
            d for d in self._state.deliveries.values() if d.status is DeliveryStatus.DEAD_LETTER
        ]


class FakeWebhooksUnitOfWork:
    def __init__(self, state: FakeWebhookState):
        self.webhooks = FakeWebhookRepository(state)

    async def __aenter__(self) -> "FakeWebhooksUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def make_uow_factory(state: FakeWebhookState):
    def factory() -> FakeWebhooksUnitOfWork:
        return FakeWebhooksUnitOfWork(state)

    return factory


class FakeWebhookSender:
    """Stub HTTP transport: fails the first `fail_times` calls, then succeeds (200)."""

    def __init__(
        self, *, fail_times: int = 0, raise_exception: bool = False, status_code: int = 200
    ):
        self.fail_times = fail_times
        self.raise_exception = raise_exception
        self.status_code = status_code
        self.calls: list[dict[str, Any]] = []

    async def send(self, *, url: str, headers: dict[str, str], body: bytes) -> int:
        self.calls.append({"url": url, "headers": headers, "body": body})
        if len(self.calls) <= self.fail_times:
            if self.raise_exception:
                raise ConnectionError("simulated network failure")
            return 500
        return self.status_code
