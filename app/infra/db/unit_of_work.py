from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.db.repositories.ledger_repository import SqlAlchemyLedgerRepository


class SqlAlchemyLedgerUnitOfWork:
    """One Postgres transaction per `async with` block, backing app.domain.ledger.unit_of_work."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]):
        self._sessionmaker = sessionmaker
        self._session: AsyncSession | None = None
        self.ledger: SqlAlchemyLedgerRepository | None = None

    async def __aenter__(self) -> Self:
        self._session = self._sessionmaker()
        self.ledger = SqlAlchemyLedgerRepository(self._session)
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

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()


def make_ledger_uow_factory(sessionmaker: async_sessionmaker[AsyncSession]):
    def factory() -> SqlAlchemyLedgerUnitOfWork:
        return SqlAlchemyLedgerUnitOfWork(sessionmaker)

    return factory
