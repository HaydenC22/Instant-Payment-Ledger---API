import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.concurrency import DEFAULT_MAX_ATTEMPTS, retry_backoff_seconds
from app.domain.idempotency.entities import IdempotencyOutcomeKind
from app.domain.idempotency.errors import IdempotencyInProgressError, IdempotencyKeyReusedError
from app.domain.ledger.entities import Direction, JournalEntry, JournalLine
from app.domain.ledger.invariants import validate_journal_entry
from app.domain.payments.entities import Payment, PaymentStatus
from app.domain.payments.state_machine import assert_transition_allowed
from app.domain.unit_of_work import UnitOfWork, UnitOfWorkFactory

IDEMPOTENCY_ENDPOINT_INITIATE_PAYMENT = "POST /payments"


class InvalidPaymentAmountError(ValueError):
    def __init__(self, amount: Decimal):
        self.amount = amount
        super().__init__(f"payment amount must be positive, got {amount}")


class SamePaymentAccountError(ValueError):
    def __init__(self, account_id: UUID):
        self.account_id = account_id
        super().__init__(f"debtor and creditor account must differ, got {account_id} for both")


class ConcurrentPaymentModificationError(RuntimeError):
    def __init__(self, payment_id: UUID, attempts: int):
        self.payment_id = payment_id
        self.attempts = attempts
        super().__init__(
            f"could not update payment {payment_id} after {attempts} attempts due to "
            "concurrent modification"
        )


def _validate_new_payment(
    amount: Decimal, debtor_account_id: UUID, creditor_account_id: UUID
) -> None:
    if amount <= 0:
        raise InvalidPaymentAmountError(amount)
    if debtor_account_id == creditor_account_id:
        raise SamePaymentAccountError(debtor_account_id)


async def _create_payment_within(
    uow: UnitOfWork,
    *,
    debtor_account_id: UUID,
    creditor_account_id: UUID,
    amount: Decimal,
    currency: str,
    end_to_end_id: str | None,
) -> Payment:
    payment = await uow.payments.create_payment(
        debtor_account_id=debtor_account_id,
        creditor_account_id=creditor_account_id,
        amount=amount,
        currency=currency,
        end_to_end_id=end_to_end_id,
    )
    await uow.payments.record_status_transition(payment.id, None, PaymentStatus.INITIATED)
    return payment


async def initiate_payment(
    uow_factory: UnitOfWorkFactory,
    *,
    debtor_account_id: UUID,
    creditor_account_id: UUID,
    amount: Decimal,
    currency: str,
    end_to_end_id: str | None = None,
) -> Payment:
    _validate_new_payment(amount, debtor_account_id, creditor_account_id)

    async with uow_factory() as uow:
        payment = await _create_payment_within(
            uow,
            debtor_account_id=debtor_account_id,
            creditor_account_id=creditor_account_id,
            amount=amount,
            currency=currency,
            end_to_end_id=end_to_end_id,
        )
        await uow.commit()
    return payment


def hash_request_body(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _payment_response_dict(payment: Payment) -> dict[str, Any]:
    return {
        "id": payment.id,
        "debtor_account_id": payment.debtor_account_id,
        "creditor_account_id": payment.creditor_account_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status,
        "version": payment.version,
        "end_to_end_id": payment.end_to_end_id,
        "fx_rate_id": payment.fx_rate_id,
    }


async def initiate_payment_idempotent(
    uow_factory: UnitOfWorkFactory,
    *,
    idempotency_key: str,
    request_body: dict[str, Any],
    debtor_account_id: UUID,
    creditor_account_id: UUID,
    amount: Decimal,
    currency: str,
    end_to_end_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Idempotent wrapper around payment initiation.

    POST /payments creates a brand-new resource, so a naive client retry after a timeout
    can silently create two payments that each later settle for real money — this is the
    one place idempotency actually prevents a double-charge in this API (the other
    lifecycle transitions are already retry-safe via the state machine: replaying an
    applied transition just 409s rather than reapplying).

    Runs as two transactions, deliberately:
      1. Claim (endpoint, key) and commit immediately, so a genuinely concurrent duplicate
         request can *see* "in progress" and get a fast 409 instead of blocking on Postgres's
         row lock for the full duration of phase 2.
      2. Create the payment and mark the claim completed together, atomically — a crash
         between "payment created" and "response recorded" can't happen, because either
         both land in that commit or neither does.
    The trade-off: if the process crashes between phase 1's commit and phase 2's commit,
    that key is orphaned "in progress" until something expires it (not implemented here —
    see docs/adr/0002-idempotency-key-storage.md).

    Returns (status_code, response_body) — on replay this is the *stored* response from
    the original attempt, not a freshly built one, so retries are byte-for-byte consistent.
    """
    _validate_new_payment(amount, debtor_account_id, creditor_account_id)
    request_hash = hash_request_body(request_body)

    async with uow_factory() as uow:
        outcome = await uow.idempotency.begin_attempt(
            key=idempotency_key,
            endpoint=IDEMPOTENCY_ENDPOINT_INITIATE_PAYMENT,
            request_hash=request_hash,
        )
        await uow.commit()

    if outcome.kind is IdempotencyOutcomeKind.REPLAY:
        assert outcome.response_status_code is not None
        assert outcome.response_body is not None
        return outcome.response_status_code, outcome.response_body

    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS_CONFLICT:
        raise IdempotencyInProgressError(idempotency_key, IDEMPOTENCY_ENDPOINT_INITIATE_PAYMENT)

    if outcome.kind is IdempotencyOutcomeKind.HASH_MISMATCH:
        raise IdempotencyKeyReusedError(idempotency_key, IDEMPOTENCY_ENDPOINT_INITIATE_PAYMENT)

    async with uow_factory() as uow:
        payment = await _create_payment_within(
            uow,
            debtor_account_id=debtor_account_id,
            creditor_account_id=creditor_account_id,
            amount=amount,
            currency=currency,
            end_to_end_id=end_to_end_id,
        )
        response_body = _payment_response_dict(payment)
        await uow.idempotency.complete_attempt(
            key=idempotency_key,
            endpoint=IDEMPOTENCY_ENDPOINT_INITIATE_PAYMENT,
            response_status_code=201,
            response_body=response_body,
        )
        await uow.commit()
    return 201, response_body


async def _transition_status_only(
    uow_factory: UnitOfWorkFactory,
    payment_id: UUID,
    to_status: PaymentStatus,
    *,
    reason: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Payment:
    """Transitions that don't move money: initiated->authorised, ->failed."""
    for attempt in range(max_attempts):
        async with uow_factory() as uow:
            payment = await uow.payments.get_payment(payment_id)
            assert_transition_allowed(payment.status, to_status)

            bumped = await uow.payments.update_payment_status(
                payment_id, payment.version, to_status
            )
            if not bumped:
                await uow.rollback()
            else:
                await uow.payments.record_status_transition(
                    payment_id, payment.status, to_status, reason
                )
                await uow.commit()
                return replace(payment, status=to_status, version=payment.version + 1)

        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_backoff_seconds(attempt))

    raise ConcurrentPaymentModificationError(payment_id, max_attempts)


async def authorise_payment(
    uow_factory: UnitOfWorkFactory, payment_id: UUID, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS
) -> Payment:
    return await _transition_status_only(
        uow_factory, payment_id, PaymentStatus.AUTHORISED, max_attempts=max_attempts
    )


async def fail_payment(
    uow_factory: UnitOfWorkFactory,
    payment_id: UUID,
    *,
    reason: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Payment:
    return await _transition_status_only(
        uow_factory, payment_id, PaymentStatus.FAILED, reason=reason, max_attempts=max_attempts
    )


async def _transition_with_ledger_entry(
    uow_factory: UnitOfWorkFactory,
    payment_id: UUID,
    to_status: PaymentStatus,
    *,
    entry_type: str,
    build_lines: Callable[[Payment], tuple[JournalLine, ...]],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Payment:
    """Transitions that move money (settle, reverse): the ledger posting and the payment
    status change happen in the same transaction, so a crash between them is impossible —
    either both land, or the whole attempt rolls back and retries.
    """
    for attempt in range(max_attempts):
        async with uow_factory() as uow:
            payment = await uow.payments.get_payment(payment_id)
            assert_transition_allowed(payment.status, to_status)

            entry = JournalEntry(
                entry_type=entry_type, payment_id=payment.id, lines=build_lines(payment)
            )
            validate_journal_entry(entry.lines)
            account_ids = entry.account_ids

            versions = await uow.ledger.get_account_versions(account_ids)
            await uow.ledger.insert_journal_entry(entry)

            conflict = False
            for account_id in account_ids:
                if not await uow.ledger.bump_account_version(account_id, versions[account_id]):
                    conflict = True
                    break

            if not conflict:
                conflict = not await uow.payments.update_payment_status(
                    payment_id, payment.version, to_status
                )

            if conflict:
                await uow.rollback()
            else:
                await uow.payments.record_status_transition(payment_id, payment.status, to_status)
                await uow.commit()
                return replace(payment, status=to_status, version=payment.version + 1)

        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_backoff_seconds(attempt))

    raise ConcurrentPaymentModificationError(payment_id, max_attempts)


def _transfer_lines(payment: Payment) -> tuple[JournalLine, ...]:
    return (
        JournalLine(payment.debtor_account_id, Direction.DEBIT, payment.amount, payment.currency),
        JournalLine(
            payment.creditor_account_id, Direction.CREDIT, payment.amount, payment.currency
        ),
    )


def _reversal_lines(payment: Payment) -> tuple[JournalLine, ...]:
    # Mirror image of _transfer_lines: flipping debit/credit undoes the settlement.
    return (
        JournalLine(payment.creditor_account_id, Direction.DEBIT, payment.amount, payment.currency),
        JournalLine(payment.debtor_account_id, Direction.CREDIT, payment.amount, payment.currency),
    )


async def settle_payment(
    uow_factory: UnitOfWorkFactory, payment_id: UUID, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS
) -> Payment:
    return await _transition_with_ledger_entry(
        uow_factory,
        payment_id,
        PaymentStatus.SETTLED,
        entry_type="transfer",
        build_lines=_transfer_lines,
        max_attempts=max_attempts,
    )


async def reverse_payment(
    uow_factory: UnitOfWorkFactory, payment_id: UUID, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS
) -> Payment:
    return await _transition_with_ledger_entry(
        uow_factory,
        payment_id,
        PaymentStatus.REVERSED,
        entry_type="reversal",
        build_lines=_reversal_lines,
        max_attempts=max_attempts,
    )
