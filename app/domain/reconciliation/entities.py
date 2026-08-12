from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class BreakType(StrEnum):
    MISSING_IN_SETTLEMENT = "missing_in_settlement"  # settled in our ledger, absent from the file
    MISSING_IN_LEDGER = "missing_in_ledger"  # in the settlement file, no matching settled payment
    AMOUNT_MISMATCH = "amount_mismatch"  # present on both sides, amount or currency disagrees


@dataclass(frozen=True, slots=True)
class SettlementRecord:
    external_ref: str
    amount: Decimal
    currency: str
    settled_at: datetime
    raw_line: str


@dataclass(frozen=True, slots=True)
class LedgerSettledPayment:
    payment_id: UUID
    external_ref: str
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class ReconciliationBreak:
    break_type: BreakType
    external_ref: str
    payment_id: UUID | None
    ledger_amount: Decimal | None
    settlement_amount: Decimal | None
    details: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    matched_count: int
    breaks: tuple[ReconciliationBreak, ...]

    @property
    def break_count(self) -> int:
        return len(self.breaks)
