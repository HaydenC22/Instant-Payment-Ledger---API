from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, UowFactory
from app.api.schemas.payments import PaymentResponse
from app.domain.ledger.repository import AccountNotFoundError
from app.domain.payments.repository import PaymentNotFoundError
from app.domain.payments.services import (
    InvalidPaymentAmountError,
    SamePaymentAccountError,
    initiate_payment,
)
from app.infra.db.repositories.ledger_repository import SqlAlchemyLedgerRepository
from app.infra.db.repositories.payment_repository import SqlAlchemyPaymentRepository
from app.infra.iso20022.pacs008 import Pacs008EmissionError, build_pacs008
from app.infra.iso20022.pain001 import Pain001ParseError, parse_pain001

router = APIRouter(prefix="/iso20022", tags=["iso20022"])


@router.post("/pain001", response_model=PaymentResponse, status_code=201)
async def ingest_pain001(
    request: Request, uow_factory: UowFactory, session: DbSession
) -> PaymentResponse:
    """Parses a pain.001 CustomerCreditTransferInitiation message and initiates the
    payment it describes, resolving the debtor/creditor account numbers it carries to
    this system's internal account records.
    """
    body = await request.body()
    try:
        transfer = parse_pain001(body)
    except Pain001ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ledger_repo = SqlAlchemyLedgerRepository(session)
    try:
        debtor = await ledger_repo.get_account_by_number(transfer.debtor_account_number)
        creditor = await ledger_repo.get_account_by_number(transfer.creditor_account_number)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"account not found: {exc.identifier}") from exc

    try:
        payment = await initiate_payment(
            uow_factory,
            debtor_account_id=debtor.id,
            creditor_account_id=creditor.id,
            amount=transfer.amount,
            currency=transfer.currency,
            end_to_end_id=transfer.end_to_end_id,
        )
    except (InvalidPaymentAmountError, SamePaymentAccountError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=404, detail="debtor or creditor account does not exist"
        ) from exc

    return PaymentResponse(**asdict(payment))


@router.get("/{payment_id}/pacs008")
async def emit_pacs008(payment_id: UUID, session: DbSession) -> Response:
    """Emits a pacs.008 FIToFICustomerCreditTransfer message for a settled payment."""
    payment_repo = SqlAlchemyPaymentRepository(session)
    ledger_repo = SqlAlchemyLedgerRepository(session)

    try:
        payment = await payment_repo.get_payment(payment_id)
    except PaymentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="payment not found") from exc

    debtor = await ledger_repo.get_account(payment.debtor_account_id)
    creditor = await ledger_repo.get_account(payment.creditor_account_id)

    try:
        xml_bytes = build_pacs008(
            payment,
            debtor_account_number=debtor.account_number,
            debtor_name=debtor.owner_name,
            creditor_account_number=creditor.account_number,
            creditor_name=creditor.owner_name,
        )
    except Pacs008EmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(content=xml_bytes, media_type="application/xml")
