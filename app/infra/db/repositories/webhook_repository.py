from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.webhooks.entities import DeliveryStatus, WebhookDelivery, WebhookSubscription
from app.infra.db.models import WebhookDeliveryModel, WebhookSubscriptionModel


def _to_domain_subscription(row: WebhookSubscriptionModel) -> WebhookSubscription:
    return WebhookSubscription(
        id=row.id,
        url=row.url,
        secret=row.secret,
        event_types=tuple(row.event_types),
        active=row.active,
    )


def _to_domain_delivery(row: WebhookDeliveryModel) -> WebhookDelivery:
    return WebhookDelivery(
        id=row.id,
        subscription_id=row.subscription_id,
        payment_id=row.payment_id,
        event_type=row.event_type,
        payload=row.payload,
        status=DeliveryStatus(row.status),
        attempt_count=row.attempt_count,
        next_attempt_at=row.next_attempt_at,
        last_error=row.last_error,
    )


class SqlAlchemyWebhookRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_subscription(
        self, *, url: str, secret: str, event_types: list[str]
    ) -> WebhookSubscription:
        row = WebhookSubscriptionModel(url=url, secret=secret, event_types=event_types)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _to_domain_subscription(row)

    async def list_active_subscriptions(self) -> list[WebhookSubscription]:
        stmt = select(WebhookSubscriptionModel).where(WebhookSubscriptionModel.active.is_(True))
        result = await self._session.execute(stmt)
        return [_to_domain_subscription(row) for row in result.scalars()]

    async def enqueue_delivery(
        self,
        *,
        subscription_id: UUID,
        payment_id: UUID | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> UUID:
        row = WebhookDeliveryModel(
            subscription_id=subscription_id,
            payment_id=payment_id,
            event_type=event_type,
            payload=payload,
        )
        self._session.add(row)
        await self._session.flush()
        return row.id

    async def list_due_deliveries(self, *, now: datetime, limit: int) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDeliveryModel)
            .where(
                WebhookDeliveryModel.status == DeliveryStatus.PENDING.value,
                WebhookDeliveryModel.next_attempt_at <= now,
            )
            .order_by(WebhookDeliveryModel.next_attempt_at)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_to_domain_delivery(row) for row in result.scalars()]

    async def mark_delivered(self, delivery_id: UUID) -> None:
        row = await self._session.get(WebhookDeliveryModel, delivery_id)
        assert row is not None
        row.status = DeliveryStatus.DELIVERED.value

    async def mark_retry(
        self, delivery_id: UUID, *, attempt_count: int, next_attempt_at: datetime, last_error: str
    ) -> None:
        row = await self._session.get(WebhookDeliveryModel, delivery_id)
        assert row is not None
        row.attempt_count = attempt_count
        row.next_attempt_at = next_attempt_at
        row.last_error = last_error

    async def mark_dead_letter(
        self, delivery_id: UUID, *, attempt_count: int, last_error: str
    ) -> None:
        row = await self._session.get(WebhookDeliveryModel, delivery_id)
        assert row is not None
        row.status = DeliveryStatus.DEAD_LETTER.value
        row.attempt_count = attempt_count
        row.last_error = last_error

    async def list_dead_letters(self) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDeliveryModel)
            .where(WebhookDeliveryModel.status == DeliveryStatus.DEAD_LETTER.value)
            .order_by(WebhookDeliveryModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [_to_domain_delivery(row) for row in result.scalars()]
