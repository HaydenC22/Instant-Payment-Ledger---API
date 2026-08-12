from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.domain.reconciliation.entities import LedgerSettledPayment, SettlementRecord
from app.domain.reconciliation.services import run_reconciliation

from .fakes import FakeReconciliationState, make_uow_factory

WINDOW_END = datetime(2026, 8, 12, tzinfo=UTC)
WINDOW_START = WINDOW_END - timedelta(hours=24)


async def test_run_reconciliation_loads_records_matches_and_persists_the_run() -> None:
    state = FakeReconciliationState()
    payment_id = uuid4()
    state.settled_payments = [
        LedgerSettledPayment(
            payment_id=payment_id, external_ref="E2E-1", amount=Decimal("10.00"), currency="SGD"
        )
    ]
    records = [
        SettlementRecord(
            external_ref="E2E-1",
            amount=Decimal("10.00"),
            currency="SGD",
            settled_at=WINDOW_END,
            raw_line="E2E-1,10.00,SGD",
        )
    ]
    batch_id = uuid4()

    run_id, result = await run_reconciliation(
        make_uow_factory(state),
        batch_id=batch_id,
        settlement_records=records,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    assert result.matched_count == 1
    assert result.breaks == ()
    assert state.loaded_records[batch_id] == records
    assert state.runs[run_id]["matched_count"] == 1
    assert state.runs[run_id]["break_count"] == 0


async def test_run_reconciliation_persists_breaks_when_ledger_and_file_disagree() -> None:
    state = FakeReconciliationState()
    state.settled_payments = [
        LedgerSettledPayment(
            payment_id=uuid4(), external_ref="ONLY-LEDGER", amount=Decimal("5.00"), currency="SGD"
        )
    ]

    run_id, result = await run_reconciliation(
        make_uow_factory(state),
        batch_id=uuid4(),
        settlement_records=[],
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    assert result.matched_count == 0
    assert len(result.breaks) == 1
    assert state.runs[run_id]["break_count"] == 1
