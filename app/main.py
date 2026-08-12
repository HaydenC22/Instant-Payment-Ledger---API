from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.accounts import router as accounts_router
from app.api.v1.health import router as health_router
from app.api.v1.iso20022 import router as iso20022_router
from app.api.v1.payments import router as payments_router
from app.api.v1.qr import router as qr_router
from app.api.v1.reconciliation import router as reconciliation_router
from app.api.v1.webhooks import router as webhooks_router
from app.config import get_settings
from app.infra.db.session import dispose_engine, get_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_engine()  # warm the connection pool on startup
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(accounts_router)
    app.include_router(payments_router)
    app.include_router(iso20022_router)
    app.include_router(webhooks_router)
    app.include_router(reconciliation_router)
    app.include_router(qr_router)
    return app


app = create_app()
