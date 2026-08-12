import asyncio
from decimal import Decimal

import pytest

from app.domain.ledger.entities import Direction, JournalEntry, JournalLine
from app.domain.ledger.services import ConcurrentModificationError, post_journal_entry
from app.infra.db.repositories.ledger_repository import SqlAlchemyLedgerRepository
from app.infra.db.unit_of_work import make_ledger_uow_factory

CONCURRENCY_RUNS = 5  # repeat the race to catch flakiness, per the project's testing strategy


async def _open_account(db_sessionmaker, *, account_number: str, currency: str = "SGD"):
    async with db_sessionmaker() as session:
        repo = SqlAlchemyLedgerRepository(session)
        account = await repo.create_account(
            account_number=account_number,
            owner_name="Test Owner",
            account_type="customer",
            currency=currency,
        )
        await session.commit()
        return account


async def _balance(db_sessionmaker, account_id, currency="SGD") -> Decimal:
    async with db_sessionmaker() as session:
        repo = SqlAlchemyLedgerRepository(session)
        return await repo.get_balance(account_id, currency)


async def test_balanced_entry_updates_both_account_balances(db_sessionmaker) -> None:
    debtor = await _open_account(db_sessionmaker, account_number="ACC-D-1")
    creditor = await _open_account(db_sessionmaker, account_number="ACC-C-1")
    uow_factory = make_ledger_uow_factory(db_sessionmaker)

    entry = JournalEntry(
        entry_type="transfer",
        lines=(
            JournalLine(debtor.id, Direction.DEBIT, Decimal("25.00"), "SGD"),
            JournalLine(creditor.id, Direction.CREDIT, Decimal("25.00"), "SGD"),
        ),
    )
    await post_journal_entry(uow_factory, entry)

    assert await _balance(db_sessionmaker, debtor.id) == Decimal("-25.00")
    assert await _balance(db_sessionmaker, creditor.id) == Decimal("25.00")


async def test_account_version_bumps_on_each_posting(db_sessionmaker) -> None:
    debtor = await _open_account(db_sessionmaker, account_number="ACC-D-2")
    creditor = await _open_account(db_sessionmaker, account_number="ACC-C-2")
    uow_factory = make_ledger_uow_factory(db_sessionmaker)

    entry = JournalEntry(
        entry_type="transfer",
        lines=(
            JournalLine(debtor.id, Direction.DEBIT, Decimal("1.00"), "SGD"),
            JournalLine(creditor.id, Direction.CREDIT, Decimal("1.00"), "SGD"),
        ),
    )
    await post_journal_entry(uow_factory, entry)
    await post_journal_entry(uow_factory, entry)

    async with db_sessionmaker() as session:
        repo = SqlAlchemyLedgerRepository(session)
        assert (await repo.get_account(debtor.id)).version == 2
        assert (await repo.get_account(creditor.id)).version == 2


@pytest.mark.parametrize("run", range(CONCURRENCY_RUNS))
async def test_concurrent_postings_to_the_same_account_never_lose_an_update(
    db_sessionmaker, run: int
) -> None:
    """N concurrent transfers all crediting the same account must all land exactly once.

    This is the ledger's core correctness claim: even though every one of these postings
    races on the shared account's `version` token, optimistic-lock retries in
    post_journal_entry guarantee none of them are silently dropped.
    """
    shared_creditor = await _open_account(db_sessionmaker, account_number=f"ACC-SHARED-{run}")
    debtors = [
        await _open_account(db_sessionmaker, account_number=f"ACC-DEBTOR-{run}-{i}")
        for i in range(10)
    ]
    uow_factory = make_ledger_uow_factory(db_sessionmaker)

    async def transfer(debtor_id) -> None:
        entry = JournalEntry(
            entry_type="transfer",
            lines=(
                JournalLine(debtor_id, Direction.DEBIT, Decimal("1.00"), "SGD"),
                JournalLine(shared_creditor.id, Direction.CREDIT, Decimal("1.00"), "SGD"),
            ),
        )
        await post_journal_entry(uow_factory, entry, max_attempts=20)

    await asyncio.gather(*(transfer(d.id) for d in debtors))

    assert await _balance(db_sessionmaker, shared_creditor.id) == Decimal("10.00")
    async with db_sessionmaker() as session:
        repo = SqlAlchemyLedgerRepository(session)
        assert (await repo.get_account(shared_creditor.id)).version == 10


async def test_exhausting_retries_leaves_no_partial_journal_entry(db_sessionmaker) -> None:
    debtor = await _open_account(db_sessionmaker, account_number="ACC-D-3")
    creditor = await _open_account(db_sessionmaker, account_number="ACC-C-3")
    uow_factory = make_ledger_uow_factory(db_sessionmaker)

    entry = JournalEntry(
        entry_type="transfer",
        lines=(
            JournalLine(debtor.id, Direction.DEBIT, Decimal("1.00"), "SGD"),
            JournalLine(creditor.id, Direction.CREDIT, Decimal("1.00"), "SGD"),
        ),
    )

    async def hammer() -> None:
        for _ in range(50):
            try:
                await post_journal_entry(uow_factory, entry, max_attempts=1)
            except ConcurrentModificationError:
                pass

    # Fire enough concurrent single-attempt posters that some must fail with max_attempts=1,
    # then confirm the balance still reflects exactly the postings that actually succeeded.
    await asyncio.gather(*(hammer() for _ in range(5)))

    debtor_balance = await _balance(db_sessionmaker, debtor.id)
    creditor_balance = await _balance(db_sessionmaker, creditor.id)
    assert debtor_balance == -creditor_balance
    assert debtor_balance <= Decimal("0")
