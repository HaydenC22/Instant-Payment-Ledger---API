from decimal import Decimal
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payments.entities import Payment, PaymentStatus
from app.domain.payments.repository import PaymentNotFoundError
from app.infra.db.models import PaymentModel, PaymentStatusHistoryModel


def _to_domain_payment(row: PaymentModel) -> Payment:
    return Payment(
        id=row.id,
        debtor_account_id=row.debtor_account_id,
        creditor_account_id=row.creditor_account_id,
        amount=row.amount,
        currency=row.currency,
        status=PaymentStatus(row.status),
        version=row.version,
        end_to_end_id=row.end_to_end_id,
        fx_rate_id=row.fx_rate_id,
        creditor_amount=row.creditor_amount,
    )


class SqlAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_payment(
        self,
        *,
        debtor_account_id: UUID,
        creditor_account_id: UUID,
        amount: Decimal,
        currency: str,
        end_to_end_id: str | None = None,
    ) -> Payment:
        row = PaymentModel(
            debtor_account_id=debtor_account_id,
            creditor_account_id=creditor_account_id,
            amount=amount,
            currency=currency,
            end_to_end_id=end_to_end_id,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _to_domain_payment(row)

    async def get_payment(self, payment_id: UUID) -> Payment:
        row = await self._session.get(PaymentModel, payment_id)
        if row is None:
            raise PaymentNotFoundError(payment_id)
        return _to_domain_payment(row)

    async def update_payment_status(
        self, payment_id: UUID, expected_version: int, new_status: PaymentStatus
    ) -> bool:
        stmt = (
            update(PaymentModel)
            .where(PaymentModel.id == payment_id, PaymentModel.version == expected_version)
            .values(status=new_status.value, version=PaymentModel.version + 1)
        )
        result = await self._session.execute(stmt)
        return result.rowcount == 1

    async def record_status_transition(
        self,
        payment_id: UUID,
        from_status: PaymentStatus | None,
        to_status: PaymentStatus,
        reason: str | None = None,
    ) -> None:
        self._session.add(
            PaymentStatusHistoryModel(
                payment_id=payment_id,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value,
                reason=reason,
            )
        )
        await self._session.flush()

    async def set_fx_details(
        self, payment_id: UUID, *, fx_rate_id: UUID, creditor_amount: Decimal
    ) -> None:
        stmt = (
            update(PaymentModel)
            .where(PaymentModel.id == payment_id)
            .values(fx_rate_id=fx_rate_id, creditor_amount=creditor_amount)
        )
        await self._session.execute(stmt)
