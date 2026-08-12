from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CreateWebhookSubscriptionRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    secret: str = Field(min_length=8, max_length=255)
    event_types: list[str] = Field(default_factory=list)


class WebhookSubscriptionResponse(BaseModel):
    id: UUID
    url: str
    event_types: list[str]
    active: bool


class WebhookDeadLetterResponse(BaseModel):
    id: UUID
    subscription_id: UUID
    payment_id: UUID | None
    event_type: str
    payload: dict[str, Any]
    attempt_count: int
    last_error: str | None
    next_attempt_at: datetime
