from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.domain.ledger.repository import LedgerRepository


class LedgerUnitOfWork(Protocol):
    """Groups one journal-posting attempt into a single atomic transaction."""

    ledger: LedgerRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


LedgerUnitOfWorkFactory = Callable[[], LedgerUnitOfWork]
