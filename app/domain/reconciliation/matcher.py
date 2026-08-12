from collections.abc import Sequence

from app.domain.reconciliation.entities import (
    BreakType,
    LedgerSettledPayment,
    ReconciliationBreak,
    ReconciliationResult,
    SettlementRecord,
)


def match(
    ledger_payments: Sequence[LedgerSettledPayment],
    settlement_records: Sequence[SettlementRecord],
) -> ReconciliationResult:
    """Reconciles settled ledger payments against an external settlement file by
    external_ref (the payment's end-to-end ID, or its own ID when none was set).

    Pure function, no I/O — this is what makes the three break types independently and
    exhaustively testable without a database.
    """
    ledger_by_ref = {p.external_ref: p for p in ledger_payments}
    settlement_by_ref = {s.external_ref: s for s in settlement_records}
    all_refs = sorted(set(ledger_by_ref) | set(settlement_by_ref))

    breaks: list[ReconciliationBreak] = []
    matched_count = 0

    for ref in all_refs:
        ledger_entry = ledger_by_ref.get(ref)
        settlement_entry = settlement_by_ref.get(ref)

        if ledger_entry is not None and settlement_entry is None:
            breaks.append(
                ReconciliationBreak(
                    break_type=BreakType.MISSING_IN_SETTLEMENT,
                    external_ref=ref,
                    payment_id=ledger_entry.payment_id,
                    ledger_amount=ledger_entry.amount,
                    settlement_amount=None,
                    details=(
                        f"payment {ledger_entry.payment_id} is settled in the ledger but "
                        "has no matching record in the settlement file"
                    ),
                )
            )
        elif settlement_entry is not None and ledger_entry is None:
            breaks.append(
                ReconciliationBreak(
                    break_type=BreakType.MISSING_IN_LEDGER,
                    external_ref=ref,
                    payment_id=None,
                    ledger_amount=None,
                    settlement_amount=settlement_entry.amount,
                    details=(
                        f"settlement file reference {ref!r} has no matching settled "
                        "payment in the ledger"
                    ),
                )
            )
        else:
            assert ledger_entry is not None and settlement_entry is not None
            amounts_match = ledger_entry.amount == settlement_entry.amount
            currencies_match = ledger_entry.currency == settlement_entry.currency
            if amounts_match and currencies_match:
                matched_count += 1
            else:
                breaks.append(
                    ReconciliationBreak(
                        break_type=BreakType.AMOUNT_MISMATCH,
                        external_ref=ref,
                        payment_id=ledger_entry.payment_id,
                        ledger_amount=ledger_entry.amount,
                        settlement_amount=settlement_entry.amount,
                        details=(
                            f"ledger shows {ledger_entry.amount} {ledger_entry.currency}, "
                            f"settlement file shows {settlement_entry.amount} "
                            f"{settlement_entry.currency}"
                        ),
                    )
                )

    return ReconciliationResult(matched_count=matched_count, breaks=tuple(breaks))
