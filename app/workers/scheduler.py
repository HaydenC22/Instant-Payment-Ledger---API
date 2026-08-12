import asyncio
import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.domain.unit_of_work import UnitOfWorkFactory
from app.domain.webhooks.dispatch import WebhookSender, dispatch_due_deliveries
from app.infra.db.session import get_sessionmaker
from app.infra.db.unit_of_work import make_uow_factory
from app.infra.webhooks.http_sender import HttpxWebhookSender

logger = logging.getLogger(__name__)

WEBHOOK_POLL_INTERVAL_SECONDS = 5


async def _dispatch_webhooks_job(
    uow_factory: UnitOfWorkFactory, sender: WebhookSender, max_attempts: int
) -> None:
    try:
        processed = await dispatch_due_deliveries(uow_factory, sender, max_attempts=max_attempts)
        if processed:
            logger.info("webhook dispatch cycle processed %d deliveries", processed)
    except Exception:
        logger.exception("webhook dispatch cycle failed")


async def run() -> None:
    """Single long-lived worker process for background jobs.

    Runs the webhook dispatch loop on a short interval. The EOD reconciliation job (M6)
    is triggered ad hoc via `docker compose run --rm worker python -m
    app.workers.reconciliation_job` rather than scheduled here continuously, matching how
    a real batch reconciliation run is operated (once per settlement cycle, not polled).
    """
    settings = get_settings()
    uow_factory = make_uow_factory(get_sessionmaker())

    async with httpx.AsyncClient(timeout=10.0) as client:
        sender = HttpxWebhookSender(client)
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _dispatch_webhooks_job,
            trigger=IntervalTrigger(seconds=WEBHOOK_POLL_INTERVAL_SECONDS),
            args=[uow_factory, sender, settings.webhook_max_attempts],
            id="webhook_dispatch",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info(
            "worker scheduler started (webhook dispatch every %ss)", WEBHOOK_POLL_INTERVAL_SECONDS
        )
        try:
            await asyncio.Event().wait()  # run until the process is stopped
        finally:
            scheduler.shutdown(wait=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
