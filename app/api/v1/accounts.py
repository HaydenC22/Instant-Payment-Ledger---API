from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.api.schemas.accounts import AccountBalanceResponse, AccountResponse, CreateAccountRequest
from app.domain.ledger.repository import AccountNotFoundError
from app.infra.db.repositories.ledger_repository import SqlAlchemyLedgerRepository

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(body: CreateAccountRequest, session: DbSession) -> AccountResponse:
    repo = SqlAlchemyLedgerRepository(session)
    try:
        account = await repo.create_account(
            account_number=body.account_number,
            owner_name=body.owner_name,
            account_type=body.account_type,
            currency=body.currency.upper(),
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="account_number already exists") from exc
    return AccountResponse(**asdict(account))


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(account_id: UUID, session: DbSession) -> AccountResponse:
    repo = SqlAlchemyLedgerRepository(session)
    try:
        account = await repo.get_account(account_id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="account not found") from exc
    return AccountResponse(**asdict(account))


@router.get("/{account_id}/balance", response_model=AccountBalanceResponse)
async def get_account_balance(
    account_id: UUID, currency: str, session: DbSession
) -> AccountBalanceResponse:
    repo = SqlAlchemyLedgerRepository(session)
    try:
        await repo.get_account(account_id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="account not found") from exc

    balance = await repo.get_balance(account_id, currency.upper())
    return AccountBalanceResponse(account_id=account_id, currency=currency.upper(), balance=balance)
