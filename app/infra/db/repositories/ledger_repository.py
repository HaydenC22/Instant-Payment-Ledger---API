from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ledger.entities import Account, JournalEntry
from app.domain.ledger.repository import AccountNotFoundError
from app.infra.db.models import AccountModel, JournalEntryModel, JournalLineModel


def _to_domain_account(row: AccountModel) -> Account:
    return Account(
        id=row.id,
        account_number=row.account_number,
        owner_name=row.owner_name,
        account_type=row.account_type,
        currency=row.currency,
        status=row.status,
        version=row.version,
    )


class SqlAlchemyLedgerRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_account(
        self, *, account_number: str, owner_name: str, account_type: str, currency: str
    ) -> Account:
        row = AccountModel(
            account_number=account_number,
            owner_name=owner_name,
            account_type=account_type,
            currency=currency,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _to_domain_account(row)

    async def get_account(self, account_id: UUID) -> Account:
        row = await self._session.get(AccountModel, account_id)
        if row is None:
            raise AccountNotFoundError(account_id)
        return _to_domain_account(row)

    async def get_account_versions(self, account_ids: Iterable[UUID]) -> dict[UUID, int]:
        account_ids = list(account_ids)
        stmt = select(AccountModel.id, AccountModel.version).where(AccountModel.id.in_(account_ids))
        result = await self._session.execute(stmt)
        versions = {row.id: row.version for row in result}
        missing = set(account_ids) - versions.keys()
        if missing:
            raise AccountNotFoundError(next(iter(missing)))
        return versions

    async def get_balance(self, account_id: UUID, currency: str) -> Decimal:
        signed = case(
            (JournalLineModel.direction == "credit", JournalLineModel.amount),
            else_=-JournalLineModel.amount,
        )
        stmt = select(func.coalesce(func.sum(signed), 0)).where(
            JournalLineModel.account_id == account_id,
            JournalLineModel.currency == currency,
        )
        result = await self._session.execute(stmt)
        return Decimal(result.scalar_one())

    async def insert_journal_entry(self, entry: JournalEntry) -> UUID:
        entry_row = JournalEntryModel(
            entry_type=entry.entry_type,
            payment_id=entry.payment_id,
            idempotency_key_id=entry.idempotency_key_id,
        )
        self._session.add(entry_row)
        await self._session.flush()

        for line in entry.lines:
            self._session.add(
                JournalLineModel(
                    journal_entry_id=entry_row.id,
                    account_id=line.account_id,
                    direction=line.direction.value,
                    amount=line.amount,
                    currency=line.currency,
                )
            )
        await self._session.flush()
        return entry_row.id

    async def bump_account_version(self, account_id: UUID, expected_version: int) -> bool:
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account_id, AccountModel.version == expected_version)
            .values(version=AccountModel.version + 1)
        )
        result = await self._session.execute(stmt)
        return result.rowcount == 1
