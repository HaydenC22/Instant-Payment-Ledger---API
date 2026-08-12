import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountModel(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_number: Mapped[str] = mapped_column(String(34), unique=True)
    owner_name: Mapped[str] = mapped_column(String(255))
    account_type: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    version: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class JournalEntryModel(Base):
    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    entry_type: Mapped[str] = mapped_column(String(30))
    idempotency_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("idempotency_keys.id"), nullable=True
    )
    posted_at: Mapped[datetime] = mapped_column(server_default=func.now())


class JournalLineModel(Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint("direction IN ('debit', 'credit')", name="ck_journal_lines_direction"),
        CheckConstraint("amount > 0", name="ck_journal_lines_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journal_entries.id"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    direction: Mapped[str] = mapped_column(String(6))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PaymentModel(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payments_amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    debtor_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    creditor_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    # fx_rate_id reference is added once that table exists (M7).
    fx_rate_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="initiated", server_default="initiated")
    end_to_end_id: Mapped[str | None] = mapped_column(String(35), nullable=True)
    version: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PaymentStatusHistoryModel(Base):
    __tablename__ = "payment_status_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    transitioned_at: Mapped[datetime] = mapped_column(server_default=func.now())
    reason: Mapped[str | None] = mapped_column(nullable=True)


class IdempotencyKeyModel(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("endpoint", "key", name="uq_idempotency_keys_endpoint_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(255))
    endpoint: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20), default="in_progress", server_default="in_progress"
    )
    response_status_code: Mapped[int | None] = mapped_column(nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class WebhookSubscriptionModel(Base):
    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(String(2048))
    secret: Mapped[str] = mapped_column(String(255))
    event_types: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), default=list, server_default="{}"
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WebhookDeliveryModel(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_subscriptions.id"), index=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    # timezone=True: compared directly against datetime.now(UTC) in dispatch queries, so
    # this one (unlike the app's other timestamp columns, which are only ever recorded and
    # displayed, never compared) must be TIMESTAMPTZ rather than naive.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# FX and reconciliation tables are added in later milestones (M6-M7) as ORM models here,
# mirroring the schema in docs/architecture.md.
