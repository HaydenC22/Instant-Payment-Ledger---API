from fastapi import APIRouter, HTTPException, Response

from app.api.deps import DbSession
from app.api.schemas.qr import GenerateQrRequest
from app.domain.ledger.repository import AccountNotFoundError
from app.infra.db.repositories.ledger_repository import SqlAlchemyLedgerRepository
from app.infra.qr.sgqr import SgqrError, build_sgqr

router = APIRouter(prefix="/qr", tags=["qr"])


@router.post("/generate")
async def generate_qr(body: GenerateQrRequest, session: DbSession) -> Response:
    """Generates an SGQR-style payment QR (PNG) for receiving a payment into `account_id`.
    The raw TLV payload is also returned in the X-SGQR-Payload header for callers that
    want it without decoding the image.
    """
    repo = SqlAlchemyLedgerRepository(session)
    try:
        account = await repo.get_account(body.account_id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="account not found") from exc

    try:
        result = build_sgqr(
            account_number=account.account_number,
            merchant_name=account.owner_name,
            merchant_city=body.merchant_city,
            currency=account.currency,
            amount=body.amount,
        )
    except SgqrError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(
        content=result.png_bytes,
        media_type="image/png",
        headers={"X-SGQR-Payload": result.payload},
    )
