from decimal import Decimal

import pytest

from app.infra.reconciliation.csv_loader import SettlementCsvError, parse_settlement_csv


def test_parses_a_valid_csv() -> None:
    content = (
        "external_ref,amount,currency,settled_at\n"
        "E2E-1,10.00,SGD,2026-08-12T00:00:00+00:00\n"
        "E2E-2,20.50,SGD,2026-08-12T01:00:00+00:00\n"
    )

    records = parse_settlement_csv(content)

    assert len(records) == 2
    assert records[0].external_ref == "E2E-1"
    assert records[0].amount == Decimal("10.00")
    assert records[0].currency == "SGD"
    assert records[1].external_ref == "E2E-2"


def test_missing_required_column_raises() -> None:
    content = "external_ref,amount,settled_at\nE2E-1,10.00,2026-08-12T00:00:00+00:00\n"
    with pytest.raises(SettlementCsvError, match="must have columns"):
        parse_settlement_csv(content)


def test_invalid_amount_raises_with_row_number() -> None:
    content = (
        "external_ref,amount,currency,settled_at\n"
        "E2E-1,not-a-number,SGD,2026-08-12T00:00:00+00:00\n"
    )
    with pytest.raises(SettlementCsvError, match="row 2"):
        parse_settlement_csv(content)


def test_invalid_date_raises() -> None:
    content = "external_ref,amount,currency,settled_at\nE2E-1,10.00,SGD,not-a-date\n"
    with pytest.raises(SettlementCsvError, match="row 2"):
        parse_settlement_csv(content)


def test_empty_csv_raises() -> None:
    content = "external_ref,amount,currency,settled_at\n"
    with pytest.raises(SettlementCsvError, match="no data rows"):
        parse_settlement_csv(content)


def test_currency_is_uppercased() -> None:
    content = "external_ref,amount,currency,settled_at\nE2E-1,10.00,sgd,2026-08-12T00:00:00+00:00\n"
    records = parse_settlement_csv(content)
    assert records[0].currency == "SGD"
