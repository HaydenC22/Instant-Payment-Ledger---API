from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ReconciliationBreakResponse(BaseModel):
    break_type: str
    external_ref: str
    payment_id: UUID | None
    ledger_amount: Decimal | None
    settlement_amount: Decimal | None
    details: str


class ReconciliationRunResponse(BaseModel):
    id: UUID
    batch_id: UUID
    matched_count: int
    break_count: int
    status: str
    breaks: list[ReconciliationBreakResponse]
