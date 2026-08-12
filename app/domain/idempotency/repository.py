from typing import Any, Protocol

from app.domain.idempotency.entities import IdempotencyOutcome


class IdempotencyRepository(Protocol):
    """Persistence port for the idempotency-key guard. Implemented by app/infra/db."""

    async def begin_attempt(
        self, *, key: str, endpoint: str, request_hash: str
    ) -> IdempotencyOutcome:
        """Atomically claims (endpoint, key) for this attempt.

        Returns STARTED if this caller now owns the attempt and should run the guarded
        operation, or REPLAY / IN_PROGRESS_CONFLICT / HASH_MISMATCH describing why it
        should not — an existing record already answers (or is answering) this key.
        """
        ...

    async def complete_attempt(
        self,
        *,
        key: str,
        endpoint: str,
        response_status_code: int,
        response_body: dict[str, Any],
    ) -> None: ...
