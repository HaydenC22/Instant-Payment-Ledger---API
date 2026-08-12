from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, UowFactory
from app.api.schemas.payments import FailPaymentRequest, InitiatePaymentRequest, PaymentResponse
from app.domain.idempotency.errors import IdempotencyInProgressError, IdempotencyKeyReusedError
from app.domain.payments.repository import PaymentNotFoundError
from app.domain.payments.services import (
    ConcurrentPaymentModificationError,
    InvalidPaymentAmountError,
    SamePaymentAccountError,
    authorise_payment,
    fail_payment,
    initiate_payment_idempotent,
    reverse_payment,
    settle_payment,
)
from app.domain.payments.state_machine import InvalidPaymentTransitionError
from app.infra.db.repositories.payment_repository import SqlAlchemyPaymentRepository

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("", response_model=PaymentResponse, status_code=201)
async def create_payment(
    body: InitiatePaymentRequest,
    uow_factory: UowFactory,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> PaymentResponse:
    try:
        _status_code, response_body = await initiate_payment_idempotent(
            uow_factory,
            idempotency_key=idempotency_key,
            request_body=body.model_dump(mode="json"),
            debtor_account_id=body.debtor_account_id,
            creditor_account_id=body.creditor_account_id,
            amount=body.amount,
            currency=body.currency.upper(),
            end_to_end_id=body.end_to_end_id,
        )
    except (InvalidPaymentAmountError, SamePaymentAccountError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IdempotencyKeyReusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IdempotencyInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=404, detail="debtor or creditor account does not exist"
        ) from exc
    return PaymentResponse(**response_body)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: UUID, session: DbSession) -> PaymentResponse:
    repo = SqlAlchemyPaymentRepository(session)
    try:
        payment = await repo.get_payment(payment_id)
    except PaymentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="payment not found") from exc
    return PaymentResponse(**asdict(payment))


@router.post("/{payment_id}/authorise", response_model=PaymentResponse)
async def authorise(payment_id: UUID, uow_factory: UowFactory) -> PaymentResponse:
    payment = await _run_transition(authorise_payment(uow_factory, payment_id))
    return PaymentResponse(**asdict(payment))


@router.post("/{payment_id}/settle", response_model=PaymentResponse)
async def settle(payment_id: UUID, uow_factory: UowFactory) -> PaymentResponse:
    payment = await _run_transition(settle_payment(uow_factory, payment_id))
    return PaymentResponse(**asdict(payment))


@router.post("/{payment_id}/reverse", response_model=PaymentResponse)
async def reverse(payment_id: UUID, uow_factory: UowFactory) -> PaymentResponse:
    payment = await _run_transition(reverse_payment(uow_factory, payment_id))
    return PaymentResponse(**asdict(payment))


@router.post("/{payment_id}/fail", response_model=PaymentResponse)
async def fail(
    payment_id: UUID, body: FailPaymentRequest, uow_factory: UowFactory
) -> PaymentResponse:
    payment = await _run_transition(fail_payment(uow_factory, payment_id, reason=body.reason))
    return PaymentResponse(**asdict(payment))


async def _run_transition(coro):
    try:
        return await coro
    except PaymentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="payment not found") from exc
    except InvalidPaymentTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConcurrentPaymentModificationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
