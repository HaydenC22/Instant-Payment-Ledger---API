from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.domain.ledger.entities import Account, JournalEntry


class AccountNotFoundError(LookupError):
    def __init__(self, account_id: UUID):
        self.account_id = account_id
        super().__init__(f"account not found: {account_id}")


class LedgerRepository(Protocol):
    """Persistence port for the ledger domain. Implemented by app/infra/db for Postgres."""

    async def create_account(
        self, *, account_number: str, owner_name: str, account_type: str, currency: str
    ) -> Account: ...

    async def get_account(self, account_id: UUID) -> Account: ...

    async def get_account_versions(self, account_ids: Iterable[UUID]) -> dict[UUID, int]: ...

    async def get_balance(self, account_id: UUID, currency: str) -> Decimal: ...

    async def insert_journal_entry(self, entry: JournalEntry) -> UUID: ...

    async def bump_account_version(self, account_id: UUID, expected_version: int) -> bool:
        """Optimistic-lock increment. Returns False if `expected_version` is stale."""
        ...
