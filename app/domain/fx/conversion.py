from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def convert_amount(amount: Decimal, rate: Decimal) -> Decimal:
    """Converts a source-currency amount into the quote currency at `rate`, rounded to
    2 decimal places (cents) using standard half-up rounding.
    """
    return (amount * rate).quantize(CENTS, rounding=ROUND_HALF_UP)
