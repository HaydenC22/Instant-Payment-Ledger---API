from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass(frozen=True, slots=True)
class JournalLine:
    account_id: UUID
    direction: Direction
    amount: Decimal
    currency: str

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction is Direction.CREDIT else -self.amount


@dataclass(frozen=True, slots=True)
class JournalEntry:
    entry_type: str
    lines: tuple[JournalLine, ...]
    payment_id: UUID | None = None
    idempotency_key_id: UUID | None = None

    @property
    def account_ids(self) -> frozenset[UUID]:
        return frozenset(line.account_id for line in self.lines)


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    account_number: str
    owner_name: str
    account_type: str
    currency: str
    status: str
    version: int


@dataclass(frozen=True, slots=True)
class AccountBalance:
    account_id: UUID
    currency: str
    balance: Decimal = field(default=Decimal("0"))
