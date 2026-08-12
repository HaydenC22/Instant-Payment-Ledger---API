from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.idempotency.errors import IdempotencyInProgressError, IdempotencyKeyReusedError
from app.domain.payments.services import (
    IDEMPOTENCY_ENDPOINT_INITIATE_PAYMENT,
    hash_request_body,
    initiate_payment_idempotent,
)

from .fakes import FakeState, make_uow_factory


def test_hash_request_body_is_stable_regardless_of_key_order() -> None:
    a = hash_request_body({"amount": "10.00", "currency": "SGD"})
    b = hash_request_body({"currency": "SGD", "amount": "10.00"})
    assert a == b


def test_hash_request_body_differs_for_different_bodies() -> None:
    a = hash_request_body({"amount": "10.00"})
    b = hash_request_body({"amount": "20.00"})
    assert a != b


async def _initiate(
    state, uow_factory, *, key="key-1", body_amount="20.00", debtor=None, creditor=None
):
    debtor = debtor or uuid4()
    creditor = creditor or uuid4()
    request_body = {
        "debtor_account_id": str(debtor),
        "creditor_account_id": str(creditor),
        "amount": body_amount,
        "currency": "SGD",
    }
    return await initiate_payment_idempotent(
        uow_factory,
        idempotency_key=key,
        request_body=request_body,
        debtor_account_id=debtor,
        creditor_account_id=creditor,
        amount=Decimal(body_amount),
        currency="SGD",
    )


async def test_first_call_creates_a_payment() -> None:
    state = FakeState()
    uow_factory = make_uow_factory(state)

    status_code, body = await _initiate(state, uow_factory)

    assert status_code == 201
    assert len(state.payments) == 1
    record = state.idempotency_records[(IDEMPOTENCY_ENDPOINT_INITIATE_PAYMENT, "key-1")]
    assert record["status"] == "completed"
    assert record["response_body"]["id"] == body["id"]


async def test_replaying_same_key_and_body_returns_stored_response_without_new_payment() -> None:
    state = FakeState()
    uow_factory = make_uow_factory(state)
    debtor, creditor = uuid4(), uuid4()

    first_status, first_body = await _initiate(state, uow_factory, debtor=debtor, creditor=creditor)
    second_status, second_body = await _initiate(
        state, uow_factory, debtor=debtor, creditor=creditor
    )

    assert second_status == first_status
    assert second_body == first_body
    assert len(state.payments) == 1


async def test_same_key_with_a_different_body_is_rejected() -> None:
    state = FakeState()
    uow_factory = make_uow_factory(state)
    debtor, creditor = uuid4(), uuid4()

    await _initiate(state, uow_factory, debtor=debtor, creditor=creditor, body_amount="20.00")

    with pytest.raises(IdempotencyKeyReusedError):
        await _initiate(state, uow_factory, debtor=debtor, creditor=creditor, body_amount="99.00")

    assert len(state.payments) == 1


async def test_a_key_still_in_progress_is_rejected_as_a_concurrent_duplicate() -> None:
    state = FakeState()
    uow_factory = make_uow_factory(state)
    state.idempotency_records[(IDEMPOTENCY_ENDPOINT_INITIATE_PAYMENT, "key-1")] = {
        "status": "in_progress",
        "request_hash": hash_request_body(
            {
                "debtor_account_id": "x",
                "creditor_account_id": "y",
                "amount": "20.00",
                "currency": "SGD",
            }
        ),
        "response_status_code": None,
        "response_body": None,
    }

    with pytest.raises(IdempotencyInProgressError):
        await _initiate(state, uow_factory, key="key-1")

    assert len(state.payments) == 0
