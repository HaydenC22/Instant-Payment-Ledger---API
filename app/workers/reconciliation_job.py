import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.domain.reconciliation.services import run_reconciliation
from app.infra.db.session import get_sessionmaker
from app.infra.db.unit_of_work import make_uow_factory
from app.infra.reconciliation.csv_loader import parse_settlement_csv


async def _run(csv_path: Path, *, window_hours: int) -> int:
    content = csv_path.read_text(encoding="utf-8")
    records = parse_settlement_csv(content)

    window_end = datetime.now(UTC)
    window_start = window_end - timedelta(hours=window_hours)
    uow_factory = make_uow_factory(get_sessionmaker())

    run_id, result = await run_reconciliation(
        uow_factory,
        batch_id=uuid4(),
        settlement_records=records,
        window_start=window_start,
        window_end=window_end,
    )

    print(
        f"Reconciliation run {run_id}: {result.matched_count} matched, "
        f"{result.break_count} break(s) (window: last {window_hours}h)"
    )
    for b in result.breaks:
        print(f"  [{b.break_type.value}] {b.external_ref}: {b.details}")

    return 1 if result.breaks else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run end-of-day reconciliation against a settlement CSV file."
    )
    parser.add_argument("csv_path", type=Path, help="path to the settlement file")
    parser.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="how far back to look for settled payments (default: 24)",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(_run(args.csv_path, window_hours=args.window_hours))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
