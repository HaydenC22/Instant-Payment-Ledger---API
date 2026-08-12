from app.domain.payments.entities import PaymentStatus

# The only legal edges. Anything not listed here — including every self-transition and
# every transition out of a terminal state — is rejected. This table is exhaustively
# tested against the full PaymentStatus x PaymentStatus product in tests/unit.
ALLOWED_TRANSITIONS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.INITIATED: frozenset({PaymentStatus.AUTHORISED, PaymentStatus.FAILED}),
    PaymentStatus.AUTHORISED: frozenset({PaymentStatus.SETTLED, PaymentStatus.FAILED}),
    PaymentStatus.SETTLED: frozenset({PaymentStatus.REVERSED}),
    PaymentStatus.REVERSED: frozenset(),
    PaymentStatus.FAILED: frozenset(),
}


class InvalidPaymentTransitionError(ValueError):
    def __init__(self, from_status: PaymentStatus, to_status: PaymentStatus):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"illegal payment transition: {from_status} -> {to_status}")


def assert_transition_allowed(from_status: PaymentStatus, to_status: PaymentStatus) -> None:
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise InvalidPaymentTransitionError(from_status, to_status)
