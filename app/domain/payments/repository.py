from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.domain.payments.entities import Payment, PaymentStatus


class PaymentNotFoundError(LookupError):
    def __init__(self, payment_id: UUID):
        self.payment_id = payment_id
        super().__init__(f"payment not found: {payment_id}")


class PaymentRepository(Protocol):
    """Persistence port for the payment lifecycle. Implemented by app/infra/db for Postgres."""

    async def create_payment(
        self,
        *,
        debtor_account_id: UUID,
        creditor_account_id: UUID,
        amount: Decimal,
        currency: str,
        end_to_end_id: str | None = None,
    ) -> Payment: ...

    async def get_payment(self, payment_id: UUID) -> Payment: ...

    async def update_payment_status(
        self, payment_id: UUID, expected_version: int, new_status: PaymentStatus
    ) -> bool:
        """Optimistic-lock increment. Returns False if `expected_version` is stale."""
        ...

    async def record_status_transition(
        self,
        payment_id: UUID,
        from_status: PaymentStatus | None,
        to_status: PaymentStatus,
        reason: str | None = None,
    ) -> None: ...

    async def set_fx_details(
        self, payment_id: UUID, *, fx_rate_id: UUID, creditor_amount: Decimal
    ) -> None:
        """Records the rate actually booked at settlement, so a later reversal can undo
        exactly what was moved rather than recomputing against a possibly-different rate.
        """
        ...
