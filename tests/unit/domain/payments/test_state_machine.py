import itertools

import pytest

from app.domain.payments.entities import PaymentStatus
from app.domain.payments.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidPaymentTransitionError,
    assert_transition_allowed,
)

ALL_PAIRS = list(itertools.product(PaymentStatus, PaymentStatus))


@pytest.mark.parametrize("from_status,to_status", ALL_PAIRS)
def test_every_status_pair_matches_the_allowed_transition_table(
    from_status: PaymentStatus, to_status: PaymentStatus
) -> None:
    """Exhaustive over the full status x status product: only whitelisted edges succeed."""
    is_allowed = to_status in ALLOWED_TRANSITIONS[from_status]

    if is_allowed:
        assert_transition_allowed(from_status, to_status)  # does not raise
    else:
        with pytest.raises(InvalidPaymentTransitionError) as exc_info:
            assert_transition_allowed(from_status, to_status)
        assert exc_info.value.from_status == from_status
        assert exc_info.value.to_status == to_status


def test_no_self_transitions_are_allowed() -> None:
    for status in PaymentStatus:
        assert status not in ALLOWED_TRANSITIONS[status]


def test_terminal_states_have_no_outgoing_transitions() -> None:
    assert ALLOWED_TRANSITIONS[PaymentStatus.FAILED] == frozenset()
    assert ALLOWED_TRANSITIONS[PaymentStatus.REVERSED] == frozenset()


def test_settlement_can_only_be_reached_from_authorised() -> None:
    reachable_from = [
        status
        for status, targets in ALLOWED_TRANSITIONS.items()
        if PaymentStatus.SETTLED in targets
    ]
    assert reachable_from == [PaymentStatus.AUTHORISED]
