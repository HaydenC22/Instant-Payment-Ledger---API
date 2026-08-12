from typing import Any
from uuid import UUID

from app.domain.unit_of_work import UnitOfWork


async def enqueue_payment_webhook_event(
    uow: UnitOfWork, *, payment_id: UUID, event_type: str, payload: dict[str, Any]
) -> None:
    """Transactional-outbox enqueue.

    Called from *within* an already-open payment-transition transaction (never given its
    own uow_factory call), so the delivery row commits atomically with the state change it
    announces — a payment can never end up settled with no corresponding delivery queued,
    or vice versa.
    """
    subscriptions = await uow.webhooks.list_active_subscriptions()
    for subscription in subscriptions:
        if subscription.event_types and event_type not in subscription.event_types:
            continue
        await uow.webhooks.enqueue_delivery(
            subscription_id=subscription.id,
            payment_id=payment_id,
            event_type=event_type,
            payload=payload,
        )
