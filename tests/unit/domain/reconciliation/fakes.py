from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.reconciliation.entities import (
    LedgerSettledPayment,
    ReconciliationBreak,
    ReconciliationResult,
    SettlementRecord,
)


@dataclass
class FakeReconciliationState:
    settled_payments: list[LedgerSettledPayment] = field(default_factory=list)
    loaded_records: dict[UUID, list[SettlementRecord]] = field(default_factory=dict)
    runs: dict[UUID, dict] = field(default_factory=dict)


class _FakeReconciliationRepository:
    def __init__(self, state: FakeReconciliationState):
        self._state = state

    async def list_settled_payments(
        self, *, window_start: datetime, window_end: datetime
    ) -> list[LedgerSettledPayment]:
        return list(self._state.settled_payments)

    async def load_settlement_records(
        self, *, batch_id: UUID, records: list[SettlementRecord]
    ) -> None:
        self._state.loaded_records[batch_id] = records

    async def record_run(self, *, batch_id: UUID, result: ReconciliationResult) -> UUID:
        run_id = uuid4()
        self._state.runs[run_id] = {
            "batch_id": batch_id,
            "matched_count": result.matched_count,
            "break_count": result.break_count,
            "breaks": result.breaks,
            "status": "completed",
        }
        return run_id

    async def get_run(self, run_id: UUID):
        return self._state.runs[run_id]

    async def list_breaks_for_run(self, run_id: UUID) -> list[ReconciliationBreak]:
        return list(self._state.runs[run_id]["breaks"])


class FakeReconciliationUnitOfWork:
    def __init__(self, state: FakeReconciliationState):
        self.reconciliation = _FakeReconciliationRepository(state)

    async def __aenter__(self) -> "FakeReconciliationUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def make_uow_factory(state: FakeReconciliationState):
    def factory() -> FakeReconciliationUnitOfWork:
        return FakeReconciliationUnitOfWork(state)

    return factory
