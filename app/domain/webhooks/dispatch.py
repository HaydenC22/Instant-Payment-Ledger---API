import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.domain.unit_of_work import UnitOfWorkFactory
from app.domain.webhooks.entities import WebhookDelivery, WebhookSubscription
from app.domain.webhooks.retry_policy import backoff_seconds

DEFAULT_MAX_DELIVERY_ATTEMPTS = 8


class WebhookSender(Protocol):
    """Transport port for actually delivering a webhook. Implemented by app/infra using httpx."""

    async def send(self, *, url: str, headers: dict[str, str], body: bytes) -> int:
        """Returns the HTTP status code. Raises on a network-level failure (timeout, DNS,
        connection refused, TLS error, ...) — dispatch_one_delivery treats that the same
        as a non-2xx response: a failed attempt to retry or eventually dead-letter.
        """
        ...


def sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _encode_payload(delivery: WebhookDelivery) -> bytes:
    return json.dumps(delivery.payload, default=str, sort_keys=True).encode("utf-8")


async def dispatch_one_delivery(
    uow_factory: UnitOfWorkFactory,
    sender: WebhookSender,
    delivery: WebhookDelivery,
    subscription: WebhookSubscription,
    *,
    max_attempts: int = DEFAULT_MAX_DELIVERY_ATTEMPTS,
) -> None:
    body = _encode_payload(delivery)
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Event": delivery.event_type,
        "X-Webhook-Signature": sign_payload(subscription.secret, body),
    }

    attempt = delivery.attempt_count + 1
    error: str | None
    try:
        status_code = await sender.send(url=subscription.url, headers=headers, body=body)
    except Exception as exc:  # noqa: BLE001 - any transport failure is a retryable delivery failure
        success, error = False, f"{type(exc).__name__}: {exc}"
    else:
        success = 200 <= status_code < 300
        error = None if success else f"HTTP {status_code}"

    async with uow_factory() as uow:
        if success:
            await uow.webhooks.mark_delivered(delivery.id)
        elif attempt >= max_attempts:
            assert error is not None
            await uow.webhooks.mark_dead_letter(
                delivery.id, attempt_count=attempt, last_error=error
            )
        else:
            assert error is not None
            next_attempt_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds(attempt - 1))
            await uow.webhooks.mark_retry(
                delivery.id,
                attempt_count=attempt,
                next_attempt_at=next_attempt_at,
                last_error=error,
            )
        await uow.commit()


async def dispatch_due_deliveries(
    uow_factory: UnitOfWorkFactory,
    sender: WebhookSender,
    *,
    limit: int = 50,
    max_attempts: int = DEFAULT_MAX_DELIVERY_ATTEMPTS,
) -> int:
    """One polling cycle: dispatch every currently-due delivery. Returns how many were
    processed, so a caller (or test) can tell an empty cycle from a busy one.
    """
    now = datetime.now(UTC)
    async with uow_factory() as uow:
        due = await uow.webhooks.list_due_deliveries(now=now, limit=limit)
        subscriptions_by_id = {s.id: s for s in await uow.webhooks.list_active_subscriptions()}

    for delivery in due:
        subscription = subscriptions_by_id.get(delivery.subscription_id)
        if subscription is None:
            continue  # subscription was deleted/deactivated after this delivery was enqueued
        await dispatch_one_delivery(
            uow_factory, sender, delivery, subscription, max_attempts=max_attempts
        )

    return len(due)
