from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class InitiatePaymentRequest(BaseModel):
    debtor_account_id: UUID
    creditor_account_id: UUID
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    end_to_end_id: str | None = Field(default=None, max_length=35)


class FailPaymentRequest(BaseModel):
    reason: str | None = None


class PaymentResponse(BaseModel):
    id: UUID
    debtor_account_id: UUID
    creditor_account_id: UUID
    amount: Decimal
    currency: str
    status: str
    version: int
    end_to_end_id: str | None
    fx_rate_id: UUID | None
    creditor_amount: Decimal | None
