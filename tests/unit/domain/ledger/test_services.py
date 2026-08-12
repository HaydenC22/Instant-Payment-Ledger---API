from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.ledger.entities import Account, Direction, JournalEntry, JournalLine
from app.domain.ledger.invariants import UnbalancedEntryError
from app.domain.ledger.services import ConcurrentModificationError, post_journal_entry

from .fakes import FakeLedgerState, make_uow_factory

ACCOUNT_A = uuid4()
ACCOUNT_B = uuid4()


def _account(account_id) -> Account:
    return Account(account_id, str(account_id)[:8], "Test", "customer", "SGD", "active", 0)


def _entry() -> JournalEntry:
    return JournalEntry(
        entry_type="transfer",
        lines=(
            JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("10.00"), "SGD"),
            JournalLine(ACCOUNT_B, Direction.CREDIT, Decimal("10.00"), "SGD"),
        ),
    )


def _state() -> FakeLedgerState:
    return FakeLedgerState(
        accounts={ACCOUNT_A: _account(ACCOUNT_A), ACCOUNT_B: _account(ACCOUNT_B)},
        versions={ACCOUNT_A: 0, ACCOUNT_B: 0},
    )


async def test_posts_successfully_with_no_contention() -> None:
    state = _state()
    entry_id = await post_journal_entry(make_uow_factory(state), _entry())

    assert entry_id is not None
    assert state.versions == {ACCOUNT_A: 1, ACCOUNT_B: 1}
    assert len(state.committed_entries) == 1
    assert state.attempts_made == 1


async def test_retries_and_succeeds_after_transient_conflict() -> None:
    state = _state()
    uow_factory = make_uow_factory(state, forced_conflict_attempts=frozenset({0}))

    entry_id = await post_journal_entry(uow_factory, _entry())

    assert entry_id is not None
    assert state.versions == {ACCOUNT_A: 1, ACCOUNT_B: 1}
    assert len(state.committed_entries) == 1
    assert state.attempts_made == 2  # one failed attempt, one that succeeded


async def test_raises_after_exhausting_retries_under_sustained_contention() -> None:
    state = _state()
    uow_factory = make_uow_factory(state, forced_conflict_attempts=frozenset({0, 1, 2}))

    with pytest.raises(ConcurrentModificationError) as exc_info:
        await post_journal_entry(uow_factory, _entry(), max_attempts=3)

    assert exc_info.value.attempts == 3
    assert exc_info.value.account_ids == {ACCOUNT_A, ACCOUNT_B}
    assert len(state.committed_entries) == 0  # nothing partially applied
    assert state.versions == {ACCOUNT_A: 0, ACCOUNT_B: 0}


async def test_rejects_unbalanced_entry_before_touching_the_unit_of_work() -> None:
    state = _state()
    bad_entry = JournalEntry(
        entry_type="transfer",
        lines=(JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("10.00"), "SGD"),),
    )

    with pytest.raises(UnbalancedEntryError):
        await post_journal_entry(make_uow_factory(state), bad_entry)

    assert state.attempts_made == 0
