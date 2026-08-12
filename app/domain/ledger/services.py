import asyncio
from uuid import UUID

from app.domain.concurrency import DEFAULT_MAX_ATTEMPTS, retry_backoff_seconds
from app.domain.ledger.entities import JournalEntry
from app.domain.ledger.invariants import validate_journal_entry
from app.domain.ledger.unit_of_work import LedgerUnitOfWorkFactory


class ConcurrentModificationError(RuntimeError):
    def __init__(self, account_ids: frozenset[UUID], attempts: int):
        self.account_ids = account_ids
        self.attempts = attempts
        super().__init__(
            f"could not post journal entry after {attempts} attempts due to concurrent "
            f"updates on accounts: {sorted(str(a) for a in account_ids)}"
        )


async def post_journal_entry(
    uow_factory: LedgerUnitOfWorkFactory,
    entry: JournalEntry,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> UUID:
    """Persist a balanced journal entry, retrying on optimistic-lock conflicts.

    Each attempt runs in its own transaction: read account versions, insert the entry
    and its lines, then bump every touched account's version token. If any bump finds
    the version already moved, the whole attempt is rolled back and retried with fresh
    versions rather than partially applying the entry.
    """
    validate_journal_entry(entry.lines)
    account_ids = entry.account_ids

    for attempt in range(max_attempts):
        async with uow_factory() as uow:
            versions = await uow.ledger.get_account_versions(account_ids)
            entry_id = await uow.ledger.insert_journal_entry(entry)

            conflict = False
            for account_id in account_ids:
                bumped = await uow.ledger.bump_account_version(account_id, versions[account_id])
                if not bumped:
                    conflict = True
                    break

            if conflict:
                await uow.rollback()
            else:
                await uow.commit()
                return entry_id

        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_backoff_seconds(attempt))

    raise ConcurrentModificationError(account_ids, max_attempts)
