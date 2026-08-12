from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.ledger.entities import Direction
from app.domain.payments.entities import PaymentStatus
from app.domain.payments.services import (
    ConcurrentPaymentModificationError,
    InvalidPaymentAmountError,
    SamePaymentAccountError,
    authorise_payment,
    fail_payment,
    initiate_payment,
    reverse_payment,
    settle_payment,
)
from app.domain.payments.state_machine import InvalidPaymentTransitionError

from .fakes import FakeState, make_uow_factory


async def test_initiate_payment_creates_it_in_initiated_status() -> None:
    state = FakeState()
    debtor, creditor = uuid4(), uuid4()

    payment = await initiate_payment(
        make_uow_factory(state),
        debtor_account_id=debtor,
        creditor_account_id=creditor,
        amount=Decimal("50.00"),
        currency="SGD",
    )

    assert payment.status == PaymentStatus.INITIATED
    assert payment.version == 0
    assert state.payments[payment.id] == payment
    assert state.status_history == [(payment.id, None, PaymentStatus.INITIATED, None)]


async def test_initiate_payment_rejects_non_positive_amount() -> None:
    with pytest.raises(InvalidPaymentAmountError):
        await initiate_payment(
            make_uow_factory(FakeState()),
            debtor_account_id=uuid4(),
            creditor_account_id=uuid4(),
            amount=Decimal("0"),
            currency="SGD",
        )


async def test_initiate_payment_rejects_same_debtor_and_creditor() -> None:
    account_id = uuid4()
    with pytest.raises(SamePaymentAccountError):
        await initiate_payment(
            make_uow_factory(FakeState()),
            debtor_account_id=account_id,
            creditor_account_id=account_id,
            amount=Decimal("10.00"),
            currency="SGD",
        )


async def test_authorise_then_settle_happy_path_posts_a_balanced_transfer() -> None:
    state = FakeState()
    payment = state.seed_payment(amount=Decimal("30.00"), currency="SGD")
    uow_factory = make_uow_factory(state)

    authorised = await authorise_payment(uow_factory, payment.id)
    assert authorised.status == PaymentStatus.AUTHORISED
    assert authorised.version == 1

    settled = await settle_payment(uow_factory, payment.id)
    assert settled.status == PaymentStatus.SETTLED
    assert settled.version == 2

    assert len(state.committed_entries) == 1
    entry = state.committed_entries[0]
    assert entry.entry_type == "transfer"
    assert entry.payment_id == payment.id
    debit_line = next(line for line in entry.lines if line.direction is Direction.DEBIT)
    credit_line = next(line for line in entry.lines if line.direction is Direction.CREDIT)
    assert debit_line.account_id == payment.debtor_account_id
    assert credit_line.account_id == payment.creditor_account_id
    assert debit_line.amount == credit_line.amount == Decimal("30.00")


async def test_settle_from_initiated_is_rejected() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.INITIATED)
    with pytest.raises(InvalidPaymentTransitionError):
        await settle_payment(make_uow_factory(state), payment.id)
    assert state.committed_entries == []


async def test_settle_from_already_settled_is_rejected() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.SETTLED)
    with pytest.raises(InvalidPaymentTransitionError):
        await settle_payment(make_uow_factory(state), payment.id)


async def test_fail_from_initiated_succeeds() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.INITIATED)
    failed = await fail_payment(make_uow_factory(state), payment.id, reason="risk decline")
    assert failed.status == PaymentStatus.FAILED
    assert state.status_history[-1] == (
        payment.id,
        PaymentStatus.INITIATED,
        PaymentStatus.FAILED,
        "risk decline",
    )


async def test_fail_from_settled_is_rejected_because_settled_is_not_terminal_via_fail() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.SETTLED)
    with pytest.raises(InvalidPaymentTransitionError):
        await fail_payment(make_uow_factory(state), payment.id)


async def test_reverse_settled_payment_posts_a_mirror_image_entry() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.SETTLED, amount=Decimal("12.50"))
    uow_factory = make_uow_factory(state)

    reversed_payment = await reverse_payment(uow_factory, payment.id)

    assert reversed_payment.status == PaymentStatus.REVERSED
    entry = state.committed_entries[0]
    assert entry.entry_type == "reversal"
    debit_line = next(line for line in entry.lines if line.direction is Direction.DEBIT)
    credit_line = next(line for line in entry.lines if line.direction is Direction.CREDIT)
    # Reversal flips the original direction: creditor is debited, debtor is credited back.
    assert debit_line.account_id == payment.creditor_account_id
    assert credit_line.account_id == payment.debtor_account_id


async def test_reverse_from_authorised_is_rejected() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.AUTHORISED)
    with pytest.raises(InvalidPaymentTransitionError):
        await reverse_payment(make_uow_factory(state), payment.id)


async def test_authorise_retries_and_succeeds_after_transient_conflict() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.INITIATED)
    uow_factory = make_uow_factory(state, forced_payment_conflicts=frozenset({0}))

    authorised = await authorise_payment(uow_factory, payment.id)

    assert authorised.status == PaymentStatus.AUTHORISED
    assert state.attempts_made == 2


async def test_authorise_raises_after_exhausting_retries() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.INITIATED)
    uow_factory = make_uow_factory(state, forced_payment_conflicts=frozenset({0, 1, 2}))

    with pytest.raises(ConcurrentPaymentModificationError):
        await authorise_payment(uow_factory, payment.id, max_attempts=3)

    assert state.payments[payment.id].status == PaymentStatus.INITIATED


async def test_settle_retries_on_ledger_conflict_without_double_posting() -> None:
    state = FakeState()
    payment = state.seed_payment(status=PaymentStatus.AUTHORISED, amount=Decimal("5.00"))
    uow_factory = make_uow_factory(state, forced_ledger_conflicts=frozenset({0}))

    settled = await settle_payment(uow_factory, payment.id)

    assert settled.status == PaymentStatus.SETTLED
    assert len(state.committed_entries) == 1
