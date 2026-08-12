from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import DbSession, UowFactory
from app.api.schemas.reconciliation import ReconciliationBreakResponse, ReconciliationRunResponse
from app.domain.reconciliation.repository import ReconciliationRunNotFoundError
from app.domain.reconciliation.services import run_reconciliation
from app.infra.db.repositories.reconciliation_repository import SqlAlchemyReconciliationRepository
from app.infra.reconciliation.csv_loader import SettlementCsvError, parse_settlement_csv

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.post("/run", response_model=ReconciliationRunResponse, status_code=201)
async def run_reconciliation_endpoint(
    request: Request, uow_factory: UowFactory, window_hours: int = 24
) -> ReconciliationRunResponse:
    """Uploads a settlement CSV (`external_ref,amount,currency,settled_at`) and reconciles
    it against payments settled in the last `window_hours` (default 24, i.e. one EOD run).
    """
    body = (await request.body()).decode("utf-8")
    try:
        records = parse_settlement_csv(body)
    except SettlementCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    window_end = datetime.now(UTC)
    window_start = window_end - timedelta(hours=window_hours)
    batch_id = uuid4()

    run_id, result = await run_reconciliation(
        uow_factory,
        batch_id=batch_id,
        settlement_records=records,
        window_start=window_start,
        window_end=window_end,
    )

    return ReconciliationRunResponse(
        id=run_id,
        batch_id=batch_id,
        matched_count=result.matched_count,
        break_count=result.break_count,
        status="completed",
        breaks=[
            ReconciliationBreakResponse(
                break_type=b.break_type.value,
                external_ref=b.external_ref,
                payment_id=b.payment_id,
                ledger_amount=b.ledger_amount,
                settlement_amount=b.settlement_amount,
                details=b.details,
            )
            for b in result.breaks
        ],
    )


@router.get("/runs/{run_id}", response_model=ReconciliationRunResponse)
async def get_reconciliation_run(run_id: UUID, session: DbSession) -> ReconciliationRunResponse:
    repo = SqlAlchemyReconciliationRepository(session)
    try:
        run = await repo.get_run(run_id)
    except ReconciliationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="reconciliation run not found") from exc
    breaks = await repo.list_breaks_for_run(run_id)

    return ReconciliationRunResponse(
        id=run.id,
        batch_id=run.batch_id,
        matched_count=run.matched_count,
        break_count=run.break_count,
        status=run.status,
        breaks=[
            ReconciliationBreakResponse(
                break_type=b.break_type.value,
                external_ref=b.external_ref,
                payment_id=b.payment_id,
                ledger_amount=b.ledger_amount,
                settlement_amount=b.settlement_amount,
                details=b.details,
            )
            for b in breaks
        ],
    )
