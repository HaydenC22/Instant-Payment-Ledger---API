from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.domain.reconciliation.entities import (
    BreakType,
    LedgerSettledPayment,
    SettlementRecord,
)
from app.domain.reconciliation.matcher import match

SETTLED_AT = datetime(2026, 8, 12, tzinfo=UTC)


def _ledger(ref: str, amount: str = "10.00", currency: str = "SGD") -> LedgerSettledPayment:
    return LedgerSettledPayment(
        payment_id=uuid4(), external_ref=ref, amount=Decimal(amount), currency=currency
    )


def _settlement(ref: str, amount: str = "10.00", currency: str = "SGD") -> SettlementRecord:
    return SettlementRecord(
        external_ref=ref,
        amount=Decimal(amount),
        currency=currency,
        settled_at=SETTLED_AT,
        raw_line=f"{ref},{amount},{currency}",
    )


def test_matching_pair_produces_no_break() -> None:
    result = match([_ledger("E2E-1")], [_settlement("E2E-1")])

    assert result.matched_count == 1
    assert result.breaks == ()


def test_payment_settled_but_absent_from_settlement_file_is_missing_in_settlement() -> None:
    result = match([_ledger("E2E-1")], [])

    assert result.matched_count == 0
    assert len(result.breaks) == 1
    b = result.breaks[0]
    assert b.break_type is BreakType.MISSING_IN_SETTLEMENT
    assert b.external_ref == "E2E-1"
    assert b.ledger_amount == Decimal("10.00")
    assert b.settlement_amount is None


def test_settlement_record_with_no_matching_payment_is_missing_in_ledger() -> None:
    result = match([], [_settlement("E2E-1")])

    assert result.matched_count == 0
    assert len(result.breaks) == 1
    b = result.breaks[0]
    assert b.break_type is BreakType.MISSING_IN_LEDGER
    assert b.external_ref == "E2E-1"
    assert b.ledger_amount is None
    assert b.settlement_amount == Decimal("10.00")


def test_amount_mismatch_between_ledger_and_settlement_file() -> None:
    result = match([_ledger("E2E-1", amount="10.00")], [_settlement("E2E-1", amount="9.99")])

    assert result.matched_count == 0
    assert len(result.breaks) == 1
    b = result.breaks[0]
    assert b.break_type is BreakType.AMOUNT_MISMATCH
    assert b.ledger_amount == Decimal("10.00")
    assert b.settlement_amount == Decimal("9.99")


def test_currency_mismatch_between_ledger_and_settlement_file_is_also_a_break() -> None:
    result = match([_ledger("E2E-1", currency="SGD")], [_settlement("E2E-1", currency="USD")])

    assert len(result.breaks) == 1
    assert result.breaks[0].break_type is BreakType.AMOUNT_MISMATCH


def test_a_realistic_batch_produces_exactly_the_expected_breaks() -> None:
    """Mirrors the plan's own scenario: seeded ledger + settlement file with each break
    type injected, asserting the reconciliation job produces exactly the expected set.
    """
    ledger_payments = [
        _ledger("MATCHED-1", amount="100.00"),
        _ledger("ONLY-IN-LEDGER", amount="50.00"),
        _ledger("MISMATCHED", amount="75.00"),
    ]
    settlement_records = [
        _settlement("MATCHED-1", amount="100.00"),
        _settlement("ONLY-IN-FILE", amount="30.00"),
        _settlement("MISMATCHED", amount="75.01"),
    ]

    result = match(ledger_payments, settlement_records)

    assert result.matched_count == 1
    breaks_by_ref = {b.external_ref: b.break_type for b in result.breaks}
    assert breaks_by_ref == {
        "ONLY-IN-LEDGER": BreakType.MISSING_IN_SETTLEMENT,
        "ONLY-IN-FILE": BreakType.MISSING_IN_LEDGER,
        "MISMATCHED": BreakType.AMOUNT_MISMATCH,
    }


def test_empty_inputs_produce_no_matches_and_no_breaks() -> None:
    result = match([], [])
    assert result.matched_count == 0
    assert result.breaks == ()
    assert result.break_count == 0
