from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.ledger.entities import Direction, JournalLine
from app.domain.ledger.invariants import (
    EmptyJournalEntryError,
    InvalidLineAmountError,
    UnbalancedEntryError,
    validate_journal_entry,
)

ACCOUNT_A = uuid4()
ACCOUNT_B = uuid4()


def test_balanced_single_currency_entry_passes() -> None:
    lines = [
        JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("10.00"), "SGD"),
        JournalLine(ACCOUNT_B, Direction.CREDIT, Decimal("10.00"), "SGD"),
    ]
    validate_journal_entry(lines)  # does not raise


def test_unbalanced_single_currency_entry_raises() -> None:
    lines = [
        JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("10.00"), "SGD"),
        JournalLine(ACCOUNT_B, Direction.CREDIT, Decimal("9.99"), "SGD"),
    ]
    with pytest.raises(UnbalancedEntryError) as exc_info:
        validate_journal_entry(lines)
    assert exc_info.value.net_by_currency == {"SGD": Decimal("-0.01")}


def test_balanced_multi_currency_entry_passes() -> None:
    lines = [
        JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("10.00"), "SGD"),
        JournalLine(ACCOUNT_B, Direction.CREDIT, Decimal("10.00"), "SGD"),
        JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("7.50"), "USD"),
        JournalLine(ACCOUNT_B, Direction.CREDIT, Decimal("7.50"), "USD"),
    ]
    validate_journal_entry(lines)  # does not raise


def test_balanced_in_one_currency_unbalanced_in_another_raises() -> None:
    lines = [
        JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("10.00"), "SGD"),
        JournalLine(ACCOUNT_B, Direction.CREDIT, Decimal("10.00"), "SGD"),
        JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("7.50"), "USD"),
        JournalLine(ACCOUNT_B, Direction.CREDIT, Decimal("5.00"), "USD"),
    ]
    with pytest.raises(UnbalancedEntryError) as exc_info:
        validate_journal_entry(lines)
    assert exc_info.value.net_by_currency == {"USD": Decimal("-2.50")}


def test_empty_entry_raises() -> None:
    with pytest.raises(EmptyJournalEntryError):
        validate_journal_entry([])


def test_zero_amount_line_raises() -> None:
    lines = [JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("0"), "SGD")]
    with pytest.raises(InvalidLineAmountError):
        validate_journal_entry(lines)


def test_negative_amount_line_raises() -> None:
    lines = [JournalLine(ACCOUNT_A, Direction.DEBIT, Decimal("-5"), "SGD")]
    with pytest.raises(InvalidLineAmountError):
        validate_journal_entry(lines)


@st.composite
def balanced_lines(draw: st.DrawFn) -> list[JournalLine]:
    currencies = draw(
        st.lists(st.sampled_from(["SGD", "USD", "EUR"]), min_size=1, max_size=3, unique=True)
    )
    lines: list[JournalLine] = []
    for currency in currencies:
        amount = draw(
            st.decimals(
                min_value="0.01",
                max_value="1000000",
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        lines.append(JournalLine(ACCOUNT_A, Direction.DEBIT, amount, currency))
        lines.append(JournalLine(ACCOUNT_B, Direction.CREDIT, amount, currency))
    draw(st.randoms()).shuffle(lines)
    return lines


@given(balanced_lines())
def test_property_any_balanced_line_set_passes(lines: list[JournalLine]) -> None:
    validate_journal_entry(lines)


@given(
    balanced_lines(),
    st.decimals(min_value="0.01", max_value="100", places=2, allow_nan=False, allow_infinity=False),
)
def test_property_perturbing_one_line_unbalances_it(
    lines: list[JournalLine], delta: Decimal
) -> None:
    perturbed = lines.copy()
    first = perturbed[0]
    perturbed[0] = JournalLine(
        first.account_id, first.direction, first.amount + delta, first.currency
    )
    with pytest.raises(UnbalancedEntryError):
        validate_journal_entry(perturbed)
