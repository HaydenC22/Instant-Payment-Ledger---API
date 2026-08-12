from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from app.domain.ledger.entities import Account, JournalEntry


@dataclass
class FakeLedgerState:
    accounts: dict[UUID, Account]
    versions: dict[UUID, int]
    committed_entries: list[JournalEntry] = field(default_factory=list)
    attempts_made: int = 0


class FakeLedgerRepository:
    def __init__(
        self,
        state: FakeLedgerState,
        pending_versions: dict[UUID, int],
        pending_entries: list[JournalEntry],
        attempt_index: int,
        forced_conflict_attempts: frozenset[int],
    ):
        self._state = state
        self._pending_versions = pending_versions
        self._pending_entries = pending_entries
        self._attempt_index = attempt_index
        self._forced_conflict_attempts = forced_conflict_attempts

    async def create_account(self, **kwargs) -> Account:  # pragma: no cover - unused by these tests
        raise NotImplementedError

    async def get_account(self, account_id: UUID) -> Account:
        return self._state.accounts[account_id]

    async def get_account_versions(self, account_ids) -> dict[UUID, int]:
        return {aid: self._state.versions[aid] for aid in account_ids}

    async def get_balance(self, account_id: UUID, currency: str) -> Decimal:  # pragma: no cover
        raise NotImplementedError

    async def insert_journal_entry(self, entry: JournalEntry) -> UUID:
        self._pending_entries.append(entry)
        return uuid4()

    async def bump_account_version(self, account_id: UUID, expected_version: int) -> bool:
        if self._attempt_index in self._forced_conflict_attempts:
            return False
        current = self._state.versions[account_id]
        if current != expected_version:
            return False
        self._pending_versions[account_id] = current + 1
        return True


class FakeLedgerUnitOfWork:
    """In-memory stand-in for the Postgres-backed unit of work, for fast domain-only tests.

    `forced_conflict_attempts` lets a test simulate another writer winning the race on
    specific (0-indexed) attempts, without needing real concurrency.
    """

    def __init__(
        self, state: FakeLedgerState, forced_conflict_attempts: frozenset[int] = frozenset()
    ):
        self._state = state
        self._forced_conflict_attempts = forced_conflict_attempts
        self.ledger: FakeLedgerRepository | None = None
        self._pending_versions: dict[UUID, int] = {}
        self._pending_entries: list[JournalEntry] = []

    async def __aenter__(self) -> "FakeLedgerUnitOfWork":
        attempt_index = self._state.attempts_made
        self._state.attempts_made += 1
        self._pending_versions = {}
        self._pending_entries = []
        self.ledger = FakeLedgerRepository(
            self._state,
            self._pending_versions,
            self._pending_entries,
            attempt_index,
            self._forced_conflict_attempts,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        self._state.versions.update(self._pending_versions)
        self._state.committed_entries.extend(self._pending_entries)

    async def rollback(self) -> None:
        self._pending_versions.clear()
        self._pending_entries.clear()


def make_uow_factory(
    state: FakeLedgerState, forced_conflict_attempts: frozenset[int] = frozenset()
):
    def factory() -> FakeLedgerUnitOfWork:
        return FakeLedgerUnitOfWork(state, forced_conflict_attempts)

    return factory
