from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.reconciliation.entities import (
    BreakType,
    LedgerSettledPayment,
    ReconciliationBreak,
    ReconciliationResult,
    SettlementRecord,
)
from app.domain.reconciliation.repository import ReconciliationRunNotFoundError
from app.infra.db.models import (
    PaymentModel,
    PaymentStatusHistoryModel,
    ReconciliationBreakModel,
    ReconciliationRunModel,
    SettlementFileRecordModel,
)


class SqlAlchemyReconciliationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_settled_payments(
        self, *, window_start: datetime, window_end: datetime
    ) -> list[LedgerSettledPayment]:
        stmt = (
            select(
                PaymentModel.id,
                PaymentModel.end_to_end_id,
                PaymentModel.amount,
                PaymentModel.currency,
            )
            .join(
                PaymentStatusHistoryModel, PaymentStatusHistoryModel.payment_id == PaymentModel.id
            )
            .where(
                PaymentStatusHistoryModel.to_status == "settled",
                PaymentStatusHistoryModel.transitioned_at >= window_start,
                PaymentStatusHistoryModel.transitioned_at < window_end,
            )
        )
        result = await self._session.execute(stmt)
        return [
            LedgerSettledPayment(
                payment_id=row.id,
                external_ref=row.end_to_end_id or str(row.id),
                amount=row.amount,
                currency=row.currency,
            )
            for row in result
        ]

    async def load_settlement_records(
        self, *, batch_id: UUID, records: list[SettlementRecord]
    ) -> None:
        for record in records:
            self._session.add(
                SettlementFileRecordModel(
                    batch_id=batch_id,
                    external_ref=record.external_ref,
                    amount=record.amount,
                    currency=record.currency,
                    settled_at=record.settled_at,
                    raw_line=record.raw_line,
                )
            )
        await self._session.flush()

    async def record_run(self, *, batch_id: UUID, result: ReconciliationResult) -> UUID:
        run_row = ReconciliationRunModel(
            batch_id=batch_id,
            matched_count=result.matched_count,
            break_count=result.break_count,
            status="completed",
        )
        self._session.add(run_row)
        await self._session.flush()

        for b in result.breaks:
            self._session.add(
                ReconciliationBreakModel(
                    run_id=run_row.id,
                    payment_id=b.payment_id,
                    external_ref=b.external_ref,
                    break_type=b.break_type.value,
                    ledger_amount=b.ledger_amount,
                    settlement_amount=b.settlement_amount,
                    details=b.details,
                )
            )
        await self._session.flush()
        return run_row.id

    async def get_run(self, run_id: UUID) -> ReconciliationRunModel:
        row = await self._session.get(ReconciliationRunModel, run_id)
        if row is None:
            raise ReconciliationRunNotFoundError(run_id)
        return row

    async def list_breaks_for_run(self, run_id: UUID) -> list[ReconciliationBreak]:
        stmt = select(ReconciliationBreakModel).where(ReconciliationBreakModel.run_id == run_id)
        result = await self._session.execute(stmt)
        return [
            ReconciliationBreak(
                break_type=BreakType(row.break_type),
                external_ref=row.external_ref,
                payment_id=row.payment_id,
                ledger_amount=row.ledger_amount,
                settlement_amount=row.settlement_amount,
                details=row.details,
            )
            for row in result.scalars()
        ]
