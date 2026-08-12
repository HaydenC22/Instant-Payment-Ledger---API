from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.session import get_sessionmaker


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
