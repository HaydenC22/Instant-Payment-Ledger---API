from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class WebhookSubscription:
    id: UUID
    url: str
    secret: str
    event_types: tuple[str, ...]
    active: bool


@dataclass(frozen=True, slots=True)
class WebhookDelivery:
    id: UUID
    subscription_id: UUID
    payment_id: UUID | None
    event_type: str
    payload: dict[str, Any]
    status: DeliveryStatus
    attempt_count: int
    next_attempt_at: datetime
    last_error: str | None
