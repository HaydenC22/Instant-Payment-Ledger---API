from dataclasses import dataclass, field, replace
from decimal import Decimal
from uuid import UUID, uuid4

from app.domain.ledger.entities import JournalEntry
from app.domain.payments.entities import Payment, PaymentStatus


@dataclass
class FakeState:
    account_versions: dict[UUID, int] = field(default_factory=dict)
    payments: dict[UUID, Payment] = field(default_factory=dict)
    committed_entries: list[JournalEntry] = field(default_factory=list)
    status_history: list[tuple] = field(default_factory=list)
    attempts_made: int = 0

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


class FakeUnitOfWork:
    """In-memory stand-in for the Postgres-backed unit of work, spanning ledger + payments."""

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
        self._pending: dict = {}

    async def __aenter__(self) -> "FakeUnitOfWork":
        attempt_index = self._state.attempts_made
        self._state.attempts_made += 1
        self._pending = {
            "account_versions": {},
            "entries": [],
            "new_payment": None,
            "payment_update": None,
            "status_history": [],
        }
        self.ledger = _FakeLedgerRepository(
            self._state, self._pending, attempt_index, self._forced_ledger_conflicts
        )
        self.payments = _FakePaymentRepository(
            self._state, self._pending, attempt_index, self._forced_payment_conflicts
        )
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
        self._state.status_history.extend(self._pending["status_history"])

    async def rollback(self) -> None:
        self._pending = {
            "account_versions": {},
            "entries": [],
            "new_payment": None,
            "payment_update": None,
            "status_history": [],
        }


def make_uow_factory(
    state: FakeState,
    forced_ledger_conflicts: frozenset[int] = frozenset(),
    forced_payment_conflicts: frozenset[int] = frozenset(),
):
    def factory() -> FakeUnitOfWork:
        return FakeUnitOfWork(state, forced_ledger_conflicts, forced_payment_conflicts)

    return factory
