from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.domain.idempotency.repository import IdempotencyRepository
from app.domain.ledger.repository import LedgerRepository
from app.domain.payments.repository import PaymentRepository


class UnitOfWork(Protocol):
    """One Postgres transaction spanning every repository touched in that transaction.

    Structurally satisfies app.domain.ledger.unit_of_work.LedgerUnitOfWork (it only needs
    `.ledger`), so post_journal_entry can be called with a UnitOfWork wherever a plain
    ledger-only unit of work is expected — e.g. from within settle_payment, which needs
    both `.ledger` and `.payments` in the same transaction.
    """

    ledger: LedgerRepository
    payments: PaymentRepository
    idempotency: IdempotencyRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]
