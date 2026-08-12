from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.domain.fx.entities import FxRate
from app.domain.fx.repository import FxRateNotFoundError
from app.domain.idempotency.entities import IdempotencyOutcome, IdempotencyOutcomeKind
from app.domain.ledger.entities import Account, JournalEntry
from app.domain.ledger.repository import AccountNotFoundError
from app.domain.payments.entities import Payment, PaymentStatus
from app.domain.webhooks.entities import WebhookSubscription


@dataclass
class FakeState:
    account_versions: dict[UUID, int] = field(default_factory=dict)
    accounts: dict[UUID, Account] = field(default_factory=dict)
    accounts_by_number: dict[str, Account] = field(default_factory=dict)
    fx_rates: dict[tuple[str, str], FxRate] = field(default_factory=dict)
    payments: dict[UUID, Payment] = field(default_factory=dict)
    committed_entries: list[JournalEntry] = field(default_factory=list)
    status_history: list[tuple] = field(default_factory=list)
    idempotency_records: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    webhook_events: list[tuple[UUID, str, dict[str, Any]]] = field(default_factory=list)
    active_subscriptions: list[WebhookSubscription] = field(default_factory=list)
    attempts_made: int = 0

    def seed_webhook_subscription(self, event_types: tuple[str, ...] = ()) -> WebhookSubscription:
        sub = WebhookSubscription(
            id=uuid4(),
            url="https://example.test/hook",
            secret="s3cr3t",
            event_types=event_types,
            active=True,
        )
        self.active_subscriptions.append(sub)
        return sub

    def seed_account(
        self,
        *,
        account_id: UUID | None = None,
        account_number: str | None = None,
        currency: str = "SGD",
    ) -> Account:
        account_id = account_id or uuid4()
        account_number = account_number or f"ACC-{str(account_id)[:8]}"
        account = Account(
            id=account_id,
            account_number=account_number,
            owner_name="Fake Owner",
            account_type="customer",
            currency=currency,
            status="active",
            version=self.account_versions.get(account_id, 0),
        )
        self.accounts[account_id] = account
        self.accounts_by_number[account_number] = account
        return account

    def seed_fx_rate(self, *, base_currency: str, quote_currency: str, rate: Decimal) -> FxRate:
        fx_rate = FxRate(
            id=uuid4(),
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=rate,
            booked_at=datetime.now(UTC),
            source="test",
        )
        self.fx_rates[(base_currency, quote_currency)] = fx_rate
        return fx_rate

    def seed_payment(self, **overrides) -> Payment:
        defaults = dict(
            id=uuid4(),
            debtor_account_id=uuid4(),
            creditor_account_id=uuid4(),
            amount=Decimal("10.00"),
            currency="SGD",
            status=PaymentStatus.INITIATED,
            version=0,
        )
        payment = Payment(**{**defaults, **overrides})
        self.payments[payment.id] = payment
        return payment


class _FakeLedgerRepository:
    def __init__(
        self, state: FakeState, pending, attempt_index: int, forced_ledger_conflicts: frozenset[int]
    ):
        self._state = state
        self._pending = pending
        self._attempt_index = attempt_index
        self._forced_ledger_conflicts = forced_ledger_conflicts

    async def get_account(self, account_id: UUID) -> Account:
        if account_id in self._state.accounts:
            return self._state.accounts[account_id]
        # Auto-vivify a default SGD account for tests that don't care about currency —
        # only FX-specific tests need to explicitly seed_account() with a real currency.
        return Account(
            id=account_id,
            account_number=f"ACC-{str(account_id)[:8]}",
            owner_name="Fake Owner",
            account_type="customer",
            currency="SGD",
            status="active",
            version=self._state.account_versions.get(account_id, 0),
        )

    async def get_account_by_number(self, account_number: str) -> Account:
        if account_number not in self._state.accounts_by_number:
            raise AccountNotFoundError(account_number)
        return self._state.accounts_by_number[account_number]

    async def get_account_versions(self, account_ids):
        return {aid: self._state.account_versions.setdefault(aid, 0) for aid in account_ids}

    async def insert_journal_entry(self, entry: JournalEntry):
        self._pending["entries"].append(entry)
        return uuid4()

    async def bump_account_version(self, account_id: UUID, expected_version: int) -> bool:
        if self._attempt_index in self._forced_ledger_conflicts:
            return False
        current = self._state.account_versions.setdefault(account_id, 0)
        if current != expected_version:
            return False
        self._pending["account_versions"][account_id] = current + 1
        return True


class _FakeFxRepository:
    def __init__(self, state: FakeState):
        self._state = state

    async def get_latest_rate(self, *, base_currency: str, quote_currency: str) -> FxRate:
        key = (base_currency, quote_currency)
        if key not in self._state.fx_rates:
            raise FxRateNotFoundError(base_currency, quote_currency)
        return self._state.fx_rates[key]


class _FakePaymentRepository:
    def __init__(
        self,
        state: FakeState,
        pending,
        attempt_index: int,
        forced_payment_conflicts: frozenset[int],
    ):
        self._state = state
        self._pending = pending
        self._attempt_index = attempt_index
        self._forced_payment_conflicts = forced_payment_conflicts

    async def create_payment(
        self, *, debtor_account_id, creditor_account_id, amount, currency, end_to_end_id=None
    ) -> Payment:
        payment = Payment(
            id=uuid4(),
            debtor_account_id=debtor_account_id,
            creditor_account_id=creditor_account_id,
            amount=amount,
            currency=currency,
            status=PaymentStatus.INITIATED,
            version=0,
            end_to_end_id=end_to_end_id,
        )
        self._pending["new_payment"] = payment
        return payment

    async def get_payment(self, payment_id: UUID) -> Payment:
        return self._state.payments[payment_id]

    async def update_payment_status(self, payment_id, expected_version, new_status) -> bool:
        if self._attempt_index in self._forced_payment_conflicts:
            return False
        current = self._state.payments[payment_id]
        if current.version != expected_version:
            return False
        self._pending["payment_update"] = (payment_id, new_status)
        return True

    async def record_status_transition(
        self, payment_id, from_status, to_status, reason=None
    ) -> None:
        self._pending["status_history"].append((payment_id, from_status, to_status, reason))

    async def set_fx_details(self, payment_id, *, fx_rate_id, creditor_amount) -> None:
        self._pending["fx_details"] = (payment_id, fx_rate_id, creditor_amount)


class _FakeIdempotencyRepository:
    def __init__(self, state: FakeState, pending):
        self._state = state
        self._pending = pending

    async def begin_attempt(
        self, *, key: str, endpoint: str, request_hash: str
    ) -> IdempotencyOutcome:
        existing = self._state.idempotency_records.get((endpoint, key))
        if existing is None:
            self._pending["idempotency_claim"] = (endpoint, key, request_hash)
            return IdempotencyOutcome(kind=IdempotencyOutcomeKind.STARTED)

        if existing["status"] == "in_progress":
            return IdempotencyOutcome(kind=IdempotencyOutcomeKind.IN_PROGRESS_CONFLICT)
        if existing["request_hash"] != request_hash:
            return IdempotencyOutcome(kind=IdempotencyOutcomeKind.HASH_MISMATCH)
        return IdempotencyOutcome(
            kind=IdempotencyOutcomeKind.REPLAY,
            response_status_code=existing["response_status_code"],
            response_body=existing["response_body"],
        )

    async def complete_attempt(
        self, *, key: str, endpoint: str, response_status_code: int, response_body: dict[str, Any]
    ) -> None:
        self._pending["idempotency_complete"] = (endpoint, key, response_status_code, response_body)


class _FakeWebhookRepository:
    """No subscriptions configured by default, so enqueue_payment_webhook_event is a no-op
    for the payment-domain tests — the webhook subsystem's own behaviour is unit-tested
    separately in tests/unit/domain/webhooks/.
    """

    def __init__(self, state: FakeState, pending):
        self._state = state
        self._pending = pending

    async def list_active_subscriptions(self):
        return list(self._state.active_subscriptions)

    async def enqueue_delivery(self, *, subscription_id, payment_id, event_type, payload) -> UUID:
        delivery_id = uuid4()
        self._pending["webhook_events"].append((payment_id, event_type, payload))
        return delivery_id


class FakeUnitOfWork:
    """In-memory stand-in for the Postgres-backed unit of work, spanning ledger + payments
    + idempotency + webhooks + fx."""

    def __init__(
        self,
        state: FakeState,
        forced_ledger_conflicts: frozenset[int] = frozenset(),
        forced_payment_conflicts: frozenset[int] = frozenset(),
    ):
        self._state = state
        self._forced_ledger_conflicts = forced_ledger_conflicts
        self._forced_payment_conflicts = forced_payment_conflicts
        self.ledger: _FakeLedgerRepository | None = None
        self.payments: _FakePaymentRepository | None = None
        self.idempotency: _FakeIdempotencyRepository | None = None
        self.webhooks: _FakeWebhookRepository | None = None
        self.fx: _FakeFxRepository | None = None
        self._pending: dict = {}

    async def __aenter__(self) -> "FakeUnitOfWork":
        attempt_index = self._state.attempts_made
        self._state.attempts_made += 1
        self._pending = {
            "account_versions": {},
            "entries": [],
            "new_payment": None,
            "payment_update": None,
            "fx_details": None,
            "status_history": [],
            "idempotency_claim": None,
            "idempotency_complete": None,
            "webhook_events": [],
        }
        self.ledger = _FakeLedgerRepository(
            self._state, self._pending, attempt_index, self._forced_ledger_conflicts
        )
        self.payments = _FakePaymentRepository(
            self._state, self._pending, attempt_index, self._forced_payment_conflicts
        )
        self.idempotency = _FakeIdempotencyRepository(self._state, self._pending)
        self.webhooks = _FakeWebhookRepository(self._state, self._pending)
        self.fx = _FakeFxRepository(self._state)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        self._state.account_versions.update(self._pending["account_versions"])
        self._state.committed_entries.extend(self._pending["entries"])
        if self._pending["new_payment"] is not None:
            payment = self._pending["new_payment"]
            self._state.payments[payment.id] = payment
        if self._pending["payment_update"] is not None:
            payment_id, new_status = self._pending["payment_update"]
            current = self._state.payments[payment_id]
            self._state.payments[payment_id] = replace(
                current, status=new_status, version=current.version + 1
            )
        if self._pending["fx_details"] is not None:
            payment_id, fx_rate_id, creditor_amount = self._pending["fx_details"]
            current = self._state.payments[payment_id]
            self._state.payments[payment_id] = replace(
                current, fx_rate_id=fx_rate_id, creditor_amount=creditor_amount
            )
        self._state.status_history.extend(self._pending["status_history"])
        if self._pending["idempotency_claim"] is not None:
            endpoint, key, request_hash = self._pending["idempotency_claim"]
            self._state.idempotency_records[(endpoint, key)] = {
                "status": "in_progress",
                "request_hash": request_hash,
                "response_status_code": None,
                "response_body": None,
            }
        if self._pending["idempotency_complete"] is not None:
            endpoint, key, status_code, body = self._pending["idempotency_complete"]
            record = self._state.idempotency_records[(endpoint, key)]
            record["status"] = "completed"
            record["response_status_code"] = status_code
            record["response_body"] = body
        self._state.webhook_events.extend(self._pending["webhook_events"])

    async def rollback(self) -> None:
        self._pending = {
            "account_versions": {},
            "entries": [],
            "new_payment": None,
            "payment_update": None,
            "fx_details": None,
            "status_history": [],
            "idempotency_claim": None,
            "idempotency_complete": None,
            "webhook_events": [],
        }


def make_uow_factory(
    state: FakeState,
    forced_ledger_conflicts: frozenset[int] = frozenset(),
    forced_payment_conflicts: frozenset[int] = frozenset(),
):
    def factory() -> FakeUnitOfWork:
        return FakeUnitOfWork(state, forced_ledger_conflicts, forced_payment_conflicts)

    return factory
