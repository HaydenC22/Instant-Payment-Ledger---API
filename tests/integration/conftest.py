from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from app.infra.db.session import _json_serializer

_MIGRATED_TABLES = (
    "idempotency_keys",
    "payment_status_history",
    "journal_lines",
    "journal_entries",
    "payments",
    "accounts",
)


@pytest.fixture(scope="session")
def postgres_container() -> AsyncIterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def engine(database_url: str):
    # Function-scoped: pytest-asyncio gives each test its own event loop by default, and
    # asyncpg connections can't be reused across loops, so the engine must not outlive one.
    eng = create_async_engine(database_url, json_serializer=_json_serializer)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(engine) -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_MIGRATED_TABLES)} RESTART IDENTITY CASCADE"))
