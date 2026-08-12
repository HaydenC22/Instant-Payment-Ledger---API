from typing import Protocol

from app.domain.fx.entities import FxRate


class FxRateNotFoundError(LookupError):
    def __init__(self, base_currency: str, quote_currency: str):
        self.base_currency = base_currency
        self.quote_currency = quote_currency
        super().__init__(f"no FX rate available for {base_currency} -> {quote_currency}")


class FxRateRepository(Protocol):
    """Persistence port for FX rates. Implemented by app/infra/db for Postgres.

    Backed by a mock rate feed (a seeded table, not a live market connection) — see
    docs/adr/0004-mock-fx-rate-feed.md.
    """

    async def get_latest_rate(self, *, base_currency: str, quote_currency: str) -> FxRate: ...
