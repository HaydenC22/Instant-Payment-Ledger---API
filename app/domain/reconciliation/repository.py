from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.reconciliation.entities import (
    LedgerSettledPayment,
    ReconciliationBreak,
    ReconciliationResult,
    SettlementRecord,
)


class ReconciliationRunNotFoundError(LookupError):
    def __init__(self, run_id: UUID):
        self.run_id = run_id
        super().__init__(f"reconciliation run not found: {run_id}")


class ReconciliationRun(Protocol):
    id: UUID
    batch_id: UUID
    matched_count: int
    break_count: int
    status: str


class ReconciliationRepository(Protocol):
    """Persistence port for reconciliation. Implemented by app/infra/db for Postgres."""

    async def list_settled_payments(
        self, *, window_start: datetime, window_end: datetime
    ) -> list[LedgerSettledPayment]: ...

    async def load_settlement_records(
        self, *, batch_id: UUID, records: list[SettlementRecord]
    ) -> None: ...

    async def record_run(self, *, batch_id: UUID, result: ReconciliationResult) -> UUID: ...

    async def get_run(self, run_id: UUID) -> ReconciliationRun: ...

    async def list_breaks_for_run(self, run_id: UUID) -> list[ReconciliationBreak]: ...
