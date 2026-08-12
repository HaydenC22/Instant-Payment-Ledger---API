from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.db.repositories.idempotency_repository import SqlAlchemyIdempotencyRepository
from app.infra.db.repositories.ledger_repository import SqlAlchemyLedgerRepository
from app.infra.db.repositories.payment_repository import SqlAlchemyPaymentRepository


class SqlAlchemyUnitOfWork:
    """One Postgres transaction per `async with` block, spanning every repository.

    Backs app.domain.unit_of_work.UnitOfWork (and, structurally, the narrower
    app.domain.ledger.unit_of_work.LedgerUnitOfWork used by post_journal_entry on its own).
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]):
        self._sessionmaker = sessionmaker
        self._session: AsyncSession | None = None
        self.ledger: SqlAlchemyLedgerRepository | None = None
        self.payments: SqlAlchemyPaymentRepository | None = None
        self.idempotency: SqlAlchemyIdempotencyRepository | None = None

    async def __aenter__(self) -> Self:
        self._session = self._sessionmaker()
        self.ledger = SqlAlchemyLedgerRepository(self._session)
        self.payments = SqlAlchemyPaymentRepository(self._session)
        self.idempotency = SqlAlchemyIdempotencyRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        if exc_type is not None:
            await self._session.rollback()
        await self._session.close()
        self._session = None
        self.ledger = None
        self.payments = None
        self.idempotency = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()


def make_uow_factory(sessionmaker: async_sessionmaker[AsyncSession]):
    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(sessionmaker)

    return factory
