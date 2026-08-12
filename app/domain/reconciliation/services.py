from datetime import datetime
from uuid import UUID

from app.domain.reconciliation.entities import ReconciliationResult, SettlementRecord
from app.domain.reconciliation.matcher import match
from app.domain.unit_of_work import UnitOfWorkFactory


async def run_reconciliation(
    uow_factory: UnitOfWorkFactory,
    *,
    batch_id: UUID,
    settlement_records: list[SettlementRecord],
    window_start: datetime,
    window_end: datetime,
) -> tuple[UUID, ReconciliationResult]:
    """Loads a settlement file's records, matches them against settled payments in the
    given window, and persists the run + any breaks — all as one auditable unit.
    """
    async with uow_factory() as uow:
        await uow.reconciliation.load_settlement_records(
            batch_id=batch_id, records=settlement_records
        )
        ledger_payments = await uow.reconciliation.list_settled_payments(
            window_start=window_start, window_end=window_end
        )
        result = match(ledger_payments, settlement_records)
        run_id = await uow.reconciliation.record_run(batch_id=batch_id, result=result)
        await uow.commit()
    return run_id, result
