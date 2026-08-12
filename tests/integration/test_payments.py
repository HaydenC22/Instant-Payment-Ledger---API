import asyncio
from decimal import Decimal

import pytest

from app.domain.payments.entities import PaymentStatus
from app.domain.payments.services import (
    authorise_payment,
    fail_payment,
    initiate_payment,
    reverse_payment,
    settle_payment,
)
from app.domain.payments.state_machine import InvalidPaymentTransitionError
from app.infra.db.repositories.ledger_repository import SqlAlchemyLedgerRepository
from app.infra.db.unit_of_work import make_uow_factory


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


async def test_full_lifecycle_moves_money_only_on_settle(db_sessionmaker) -> None:
    debtor = await _open_account(db_sessionmaker, account_number="PAY-D-1")
    creditor = await _open_account(db_sessionmaker, account_number="PAY-C-1")
    uow_factory = make_uow_factory(db_sessionmaker)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("40.00"),
        currency="SGD",
    )
    assert payment.status == PaymentStatus.INITIATED

    await authorise_payment(uow_factory, payment.id)
    # Authorisation alone must not move money.
    assert await _balance(db_sessionmaker, debtor.id) == Decimal("0")
    assert await _balance(db_sessionmaker, creditor.id) == Decimal("0")

    settled = await settle_payment(uow_factory, payment.id)
    assert settled.status == PaymentStatus.SETTLED
    assert await _balance(db_sessionmaker, debtor.id) == Decimal("-40.00")
    assert await _balance(db_sessionmaker, creditor.id) == Decimal("40.00")


async def test_reverse_settled_payment_undoes_the_balances(db_sessionmaker) -> None:
    debtor = await _open_account(db_sessionmaker, account_number="PAY-D-2")
    creditor = await _open_account(db_sessionmaker, account_number="PAY-C-2")
    uow_factory = make_uow_factory(db_sessionmaker)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("15.00"),
        currency="SGD",
    )
    await authorise_payment(uow_factory, payment.id)
    await settle_payment(uow_factory, payment.id)

    reversed_payment = await reverse_payment(uow_factory, payment.id)

    assert reversed_payment.status == PaymentStatus.REVERSED
    assert await _balance(db_sessionmaker, debtor.id) == Decimal("0")
    assert await _balance(db_sessionmaker, creditor.id) == Decimal("0")


async def test_settling_before_authorising_is_rejected_and_moves_no_money(db_sessionmaker) -> None:
    debtor = await _open_account(db_sessionmaker, account_number="PAY-D-3")
    creditor = await _open_account(db_sessionmaker, account_number="PAY-C-3")
    uow_factory = make_uow_factory(db_sessionmaker)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("5.00"),
        currency="SGD",
    )

    with pytest.raises(InvalidPaymentTransitionError):
        await settle_payment(uow_factory, payment.id)

    assert await _balance(db_sessionmaker, debtor.id) == Decimal("0")
    assert await _balance(db_sessionmaker, creditor.id) == Decimal("0")


async def test_failing_an_initiated_payment_leaves_it_terminal(db_sessionmaker) -> None:
    debtor = await _open_account(db_sessionmaker, account_number="PAY-D-4")
    creditor = await _open_account(db_sessionmaker, account_number="PAY-C-4")
    uow_factory = make_uow_factory(db_sessionmaker)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("5.00"),
        currency="SGD",
    )
    failed = await fail_payment(uow_factory, payment.id, reason="compliance hold")
    assert failed.status == PaymentStatus.FAILED

    with pytest.raises(InvalidPaymentTransitionError):
        await authorise_payment(uow_factory, payment.id)


async def test_concurrent_authorise_calls_on_the_same_payment_apply_exactly_once(
    db_sessionmaker,
) -> None:
    debtor = await _open_account(db_sessionmaker, account_number="PAY-D-5")
    creditor = await _open_account(db_sessionmaker, account_number="PAY-C-5")
    uow_factory = make_uow_factory(db_sessionmaker)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("5.00"),
        currency="SGD",
    )

    results = await asyncio.gather(
        *(authorise_payment(uow_factory, payment.id, max_attempts=20) for _ in range(10)),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1
    assert all(isinstance(f, InvalidPaymentTransitionError) for f in failures)
    assert len(failures) == 9


async def test_concurrent_settle_calls_on_the_same_payment_move_money_exactly_once(
    db_sessionmaker,
) -> None:
    """Racing settle_payment N times on one payment must post exactly one transfer.

    Whichever caller's version-CAS wins commits the transfer and flips the payment to
    settled; every other caller retries, re-reads the now-settled payment, and is
    rejected by the state machine rather than posting a second transfer.
    """
    debtor = await _open_account(db_sessionmaker, account_number="PAY-D-6")
    creditor = await _open_account(db_sessionmaker, account_number="PAY-C-6")
    uow_factory = make_uow_factory(db_sessionmaker)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=Decimal("5.00"),
        currency="SGD",
    )
    await authorise_payment(uow_factory, payment.id)

    results = await asyncio.gather(
        *(settle_payment(uow_factory, payment.id, max_attempts=20) for _ in range(10)),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1
    assert all(isinstance(f, InvalidPaymentTransitionError) for f in failures)
    assert await _balance(db_sessionmaker, debtor.id) == Decimal("-5.00")
    assert await _balance(db_sessionmaker, creditor.id) == Decimal("5.00")
