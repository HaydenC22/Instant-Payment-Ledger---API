import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from app.domain.reconciliation.entities import SettlementRecord

REQUIRED_COLUMNS = {"external_ref", "amount", "currency", "settled_at"}


class SettlementCsvError(ValueError):
    pass


def parse_settlement_csv(content: str) -> list[SettlementRecord]:
    """Parses a settlement file: `external_ref,amount,currency,settled_at` (ISO 8601), one
    row per settled transaction the network reports. Deliberately simple — a real
    settlement feed's exact format varies by network/scheme; this is the shape the rest
    of the reconciliation pipeline is built against.
    """
    reader = csv.DictReader(StringIO(content))
    if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        raise SettlementCsvError(f"CSV must have columns: {sorted(REQUIRED_COLUMNS)}")

    records: list[SettlementRecord] = []
    for line_number, row in enumerate(reader, start=2):  # header is line 1
        try:
            records.append(
                SettlementRecord(
                    external_ref=row["external_ref"].strip(),
                    amount=Decimal(row["amount"].strip()),
                    currency=row["currency"].strip().upper(),
                    settled_at=datetime.fromisoformat(row["settled_at"].strip()),
                    raw_line=",".join(f"{k}={v}" for k, v in row.items()),
                )
            )
        except (InvalidOperation, ValueError) as exc:
            raise SettlementCsvError(f"row {line_number}: {exc}") from exc

    if not records:
        raise SettlementCsvError("settlement file contains no data rows")

    return records
