from fastapi import APIRouter

from app.api.deps import DbSession
from app.api.schemas.webhooks import (
    CreateWebhookSubscriptionRequest,
    WebhookDeadLetterResponse,
    WebhookSubscriptionResponse,
)
from app.infra.db.repositories.webhook_repository import SqlAlchemyWebhookRepository

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/subscriptions", response_model=WebhookSubscriptionResponse, status_code=201)
async def create_subscription(
    body: CreateWebhookSubscriptionRequest, session: DbSession
) -> WebhookSubscriptionResponse:
    repo = SqlAlchemyWebhookRepository(session)
    subscription = await repo.create_subscription(
        url=body.url, secret=body.secret, event_types=body.event_types
    )
    await session.commit()
    # secret is intentionally never echoed back — only the caller who set it should know it.
    return WebhookSubscriptionResponse(
        id=subscription.id,
        url=subscription.url,
        event_types=list(subscription.event_types),
        active=subscription.active,
    )


@router.get("/dead-letters", response_model=list[WebhookDeadLetterResponse])
async def list_dead_letters(session: DbSession) -> list[WebhookDeadLetterResponse]:
    repo = SqlAlchemyWebhookRepository(session)
    deliveries = await repo.list_dead_letters()
    return [
        WebhookDeadLetterResponse(
            id=d.id,
            subscription_id=d.subscription_id,
            payment_id=d.payment_id,
            event_type=d.event_type,
            payload=d.payload,
            attempt_count=d.attempt_count,
            last_error=d.last_error,
            next_attempt_at=d.next_attempt_at,
        )
        for d in deliveries
    ]
