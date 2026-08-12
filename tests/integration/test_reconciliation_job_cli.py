from decimal import Decimal
from uuid import UUID

from app.domain.payments.services import authorise_payment, initiate_payment, settle_payment
from app.infra.db.repositories.ledger_repository import SqlAlchemyLedgerRepository
from app.infra.db.unit_of_work import make_uow_factory
from app.workers import reconciliation_job


async def _open_account(db_sessionmaker, *, account_number: str) -> str:
    async with db_sessionmaker() as session:
        repo = SqlAlchemyLedgerRepository(session)
        account = await repo.create_account(
            account_number=account_number,
            owner_name="Test Owner",
            account_type="customer",
            currency="SGD",
        )
        await session.commit()
        return str(account.id)


async def test_cli_run_against_a_matching_settlement_file_returns_zero(
    db_sessionmaker, monkeypatch, tmp_path
) -> None:
    debtor_id = await _open_account(db_sessionmaker, account_number="CLI-D-1")
    creditor_id = await _open_account(db_sessionmaker, account_number="CLI-C-1")
    uow_factory = make_uow_factory(db_sessionmaker)

    payment = await initiate_payment(
        uow_factory,
        debtor_account_id=UUID(debtor_id),
        creditor_account_id=UUID(creditor_id),
        amount=Decimal("12.00"),
        currency="SGD",
        end_to_end_id="CLI-E2E-1",
    )
    await authorise_payment(uow_factory, payment.id)
    await settle_payment(uow_factory, payment.id)

    csv_path = tmp_path / "settlement.csv"
    csv_path.write_text(
        "external_ref,amount,currency,settled_at\n"
        "CLI-E2E-1,12.00,SGD,2026-08-12T00:00:00+00:00\n"
    )

    monkeypatch.setattr(reconciliation_job, "get_sessionmaker", lambda: db_sessionmaker)

    exit_code = await reconciliation_job._run(csv_path, window_hours=24)

    assert exit_code == 0


async def test_cli_run_with_a_break_returns_nonzero(db_sessionmaker, monkeypatch, tmp_path) -> None:
    csv_path = tmp_path / "settlement.csv"
    csv_path.write_text(
        "external_ref,amount,currency,settled_at\n"
        "NO-SUCH-PAYMENT,5.00,SGD,2026-08-12T00:00:00+00:00\n"
    )

    monkeypatch.setattr(reconciliation_job, "get_sessionmaker", lambda: db_sessionmaker)

    exit_code = await reconciliation_job._run(csv_path, window_hours=24)

    assert exit_code == 1
