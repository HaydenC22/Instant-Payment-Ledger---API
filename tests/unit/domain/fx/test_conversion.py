from decimal import Decimal

from app.domain.fx.conversion import convert_amount


def test_convert_amount_multiplies_and_rounds_to_cents() -> None:
    assert convert_amount(Decimal("100.00"), Decimal("0.74")) == Decimal("74.00")


def test_convert_amount_rounds_half_up() -> None:
    assert convert_amount(Decimal("10.00"), Decimal("0.745")) == Decimal("7.45")
    assert convert_amount(Decimal("1.00"), Decimal("0.005")) == Decimal("0.01")


def test_convert_amount_with_identity_rate_is_unchanged() -> None:
    assert convert_amount(Decimal("42.50"), Decimal("1")) == Decimal("42.50")
