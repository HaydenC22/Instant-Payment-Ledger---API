from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.idempotency.entities import IdempotencyOutcome, IdempotencyOutcomeKind
from app.infra.db.models import IdempotencyKeyModel


class SqlAlchemyIdempotencyRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def begin_attempt(
        self, *, key: str, endpoint: str, request_hash: str
    ) -> IdempotencyOutcome:
        stmt = (
            pg_insert(IdempotencyKeyModel)
            .values(key=key, endpoint=endpoint, request_hash=request_hash, status="in_progress")
            .on_conflict_do_nothing(constraint="uq_idempotency_keys_endpoint_key")
            .returning(IdempotencyKeyModel.id)
        )
        result = await self._session.execute(stmt)
        if result.first() is not None:
            return IdempotencyOutcome(kind=IdempotencyOutcomeKind.STARTED)

        # (endpoint, key) already exists — by the time our INSERT's conflict resolved, the
        # other transaction that owns it had already committed (Postgres blocks concurrent
        # inserts on the same unique key until the blocker commits or rolls back), so this
        # read reliably reflects that transaction's final state.
        existing_stmt = select(IdempotencyKeyModel).where(
            IdempotencyKeyModel.endpoint == endpoint, IdempotencyKeyModel.key == key
        )
        existing = (await self._session.execute(existing_stmt)).scalar_one()

        if existing.status == "in_progress":
            return IdempotencyOutcome(kind=IdempotencyOutcomeKind.IN_PROGRESS_CONFLICT)

        if existing.request_hash != request_hash:
            return IdempotencyOutcome(kind=IdempotencyOutcomeKind.HASH_MISMATCH)

        return IdempotencyOutcome(
            kind=IdempotencyOutcomeKind.REPLAY,
            response_status_code=existing.response_status_code,
            response_body=existing.response_body,
        )

    async def complete_attempt(
        self,
        *,
        key: str,
        endpoint: str,
        response_status_code: int,
        response_body: dict[str, Any],
    ) -> None:
        stmt = (
            update(IdempotencyKeyModel)
            .where(IdempotencyKeyModel.endpoint == endpoint, IdempotencyKeyModel.key == key)
            .values(
                status="completed",
                response_status_code=response_status_code,
                response_body=response_body,
                completed_at=func.now(),
            )
        )
        await self._session.execute(stmt)
