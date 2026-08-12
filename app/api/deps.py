from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.unit_of_work import UnitOfWorkFactory
from app.infra.db.session import get_sessionmaker
from app.infra.db.unit_of_work import make_uow_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_uow_factory() -> UnitOfWorkFactory:
    # Domain services open one transaction per attempt (for optimistic-lock retries), so
    # this hands them a factory bound to the global sessionmaker rather than a single
    # request-scoped session.
    return make_uow_factory(get_sessionmaker())


UowFactory = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]
