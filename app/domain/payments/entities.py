from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class PaymentStatus(StrEnum):
    INITIATED = "initiated"
    AUTHORISED = "authorised"
    SETTLED = "settled"
    REVERSED = "reversed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Payment:
    id: UUID
    debtor_account_id: UUID
    creditor_account_id: UUID
    amount: Decimal
    currency: str
    status: PaymentStatus
    version: int
    end_to_end_id: str | None = None
    fx_rate_id: UUID | None = None
