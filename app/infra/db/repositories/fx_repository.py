from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.fx.entities import FxRate
from app.domain.fx.repository import FxRateNotFoundError
from app.infra.db.models import FxRateModel


class SqlAlchemyFxRateRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_latest_rate(self, *, base_currency: str, quote_currency: str) -> FxRate:
        stmt = (
            select(FxRateModel)
            .where(
                FxRateModel.base_currency == base_currency,
                FxRateModel.quote_currency == quote_currency,
            )
            .order_by(FxRateModel.booked_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise FxRateNotFoundError(base_currency, quote_currency)
        return FxRate(
            id=row.id,
            base_currency=row.base_currency,
            quote_currency=row.quote_currency,
            rate=row.rate,
            booked_at=row.booked_at,
            source=row.source,
        )
