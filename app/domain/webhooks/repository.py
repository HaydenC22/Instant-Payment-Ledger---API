from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.webhooks.entities import WebhookDelivery, WebhookSubscription


class WebhookRepository(Protocol):
    """Persistence port for webhook subscriptions and deliveries. Implemented by app/infra/db."""

    async def create_subscription(
        self, *, url: str, secret: str, event_types: list[str]
    ) -> WebhookSubscription: ...

    async def list_active_subscriptions(self) -> list[WebhookSubscription]: ...

    async def enqueue_delivery(
        self,
        *,
        subscription_id: UUID,
        payment_id: UUID | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> UUID: ...

    async def list_due_deliveries(self, *, now: datetime, limit: int) -> list[WebhookDelivery]: ...

    async def mark_delivered(self, delivery_id: UUID) -> None: ...

    async def mark_retry(
        self, delivery_id: UUID, *, attempt_count: int, next_attempt_at: datetime, last_error: str
    ) -> None: ...

    async def mark_dead_letter(
        self, delivery_id: UUID, *, attempt_count: int, last_error: str
    ) -> None: ...

    async def list_dead_letters(self) -> list[WebhookDelivery]: ...
