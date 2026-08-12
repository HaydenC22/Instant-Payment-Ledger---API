from dataclasses import replace
from decimal import Decimal

import pytest

from app.domain.fx.repository import FxRateNotFoundError
from app.domain.ledger.entities import Account, Direction
from app.domain.payments.entities import PaymentStatus
from app.domain.payments.services import (
    FX_SUSPENSE_ACCOUNT_NUMBER,
    PaymentCurrencyMismatchError,
    authorise_payment,
    initiate_payment,
    reverse_payment,
    settle_payment,
)

from .fakes import FakeState, make_uow_factory


def _seeded_state(rate: str = "0.74") -> tuple[FakeState, Account, Account]:
    state = FakeState()
    debtor = state.seed_account(currency="SGD")
    creditor = state.seed_account(currency="USD")
    state.seed_account(account_number=FX_SUSPENSE_ACCOUNT_NUMBER, currency="SGD")
    state.seed_fx_rate(base_currency="SGD", quote_currency="USD", rate=Decimal(rate))
    return state, debtor, creditor


async def test_initiate_payment_rejects_currency_not_matching_debtor_account() -> None:
    state = FakeState()
    debtor = state.seed_account(currency="SGD")
    creditor = state.seed_account(currency="USD")

    with pytest.raises(PaymentCurrencyMismatchError):
        await initiate_payment(
            make_uow_factory(state),
            debtor_account_id=debtor.id,
            creditor_account_id=creditor.id,
            amount=Decimal("10.00"),
            currency="USD",  # doesn't match debtor's SGD account
        )


async def test_settling_a_cross_currency_payment_books_a_four_line_fx_entry() -> None:
    state, debtor, creditor = _seeded_state(rate="0.74")
    uow_factory = make_uow_factory(state)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    await authorise_payment(uow_factory, payment.id)
    settled = await settle_payment(uow_factory, payment.id)

    assert settled.fx_rate_id is not None
    assert settled.creditor_amount == Decimal("74.00")

    assert len(state.committed_entries) == 1
    entry = state.committed_entries[0]
    assert entry.entry_type == "fx_conversion"
    assert len(entry.lines) == 4

    suspense = state.accounts_by_number[FX_SUSPENSE_ACCOUNT_NUMBER]

    sgd_lines = [line for line in entry.lines if line.currency == "SGD"]
    usd_lines = [line for line in entry.lines if line.currency == "USD"]
    assert len(sgd_lines) == 2
    assert len(usd_lines) == 2

    sgd_debit = next(line for line in sgd_lines if line.direction is Direction.DEBIT)
    sgd_credit = next(line for line in sgd_lines if line.direction is Direction.CREDIT)
    assert sgd_debit.account_id == debtor.id
    assert sgd_debit.amount == Decimal("100.00")
    assert sgd_credit.account_id == suspense.id
    assert sgd_credit.amount == Decimal("100.00")

    usd_debit = next(line for line in usd_lines if line.direction is Direction.DEBIT)
    usd_credit = next(line for line in usd_lines if line.direction is Direction.CREDIT)
    assert usd_debit.account_id == suspense.id
    assert usd_debit.amount == Decimal("74.00")
    assert usd_credit.account_id == creditor.id
    assert usd_credit.amount == Decimal("74.00")


async def test_settling_a_cross_currency_payment_without_a_configured_rate_raises() -> None:
    state = FakeState()
    debtor = state.seed_account(currency="SGD")
    creditor = state.seed_account(currency="EUR")  # no SGD->EUR rate seeded
    state.seed_account(account_number=FX_SUSPENSE_ACCOUNT_NUMBER, currency="SGD")
    uow_factory = make_uow_factory(state)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("10.00"),
        currency="SGD",
    )
    await authorise_payment(uow_factory, payment.id)

    with pytest.raises(FxRateNotFoundError):
        await settle_payment(uow_factory, payment.id)


async def test_reversing_an_fx_payment_uses_the_originally_booked_amount_not_a_fresh_rate() -> None:
    state, debtor, creditor = _seeded_state(rate="0.74")
    uow_factory = make_uow_factory(state)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    await authorise_payment(uow_factory, payment.id)
    await settle_payment(uow_factory, payment.id)

    # Rate moves after settlement — the reversal must still undo exactly 74.00 USD.
    original_rate = state.fx_rates[("SGD", "USD")]
    state.fx_rates[("SGD", "USD")] = replace(original_rate, rate=Decimal("0.50"))

    reversed_payment = await reverse_payment(uow_factory, payment.id)
    assert reversed_payment.status == PaymentStatus.REVERSED

    reversal_entry = state.committed_entries[-1]
    assert reversal_entry.entry_type == "fx_conversion_reversal"
    usd_lines = [line for line in reversal_entry.lines if line.currency == "USD"]
    assert all(line.amount == Decimal("74.00") for line in usd_lines)

    suspense = state.accounts_by_number[FX_SUSPENSE_ACCOUNT_NUMBER]
    sgd_lines = [line for line in reversal_entry.lines if line.currency == "SGD"]
    debit = next(line for line in sgd_lines if line.direction is Direction.DEBIT)
    credit = next(line for line in sgd_lines if line.direction is Direction.CREDIT)
    assert debit.account_id == suspense.id
    assert credit.account_id == debtor.id


async def test_same_currency_settlement_does_not_touch_the_suspense_account() -> None:
    state = FakeState()
    debtor = state.seed_account(currency="SGD")
    creditor = state.seed_account(currency="SGD")
    uow_factory = make_uow_factory(state)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("20.00"),
        currency="SGD",
    )
    await authorise_payment(uow_factory, payment.id)
    settled = await settle_payment(uow_factory, payment.id)

    assert settled.fx_rate_id is None
    assert settled.creditor_amount is None
    entry = state.committed_entries[0]
    assert entry.entry_type == "transfer"
    assert len(entry.lines) == 2
