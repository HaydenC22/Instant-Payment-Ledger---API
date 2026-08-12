from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FxRate:
    id: UUID
    base_currency: str
    quote_currency: str
    rate: Decimal
    booked_at: datetime
    source: str
