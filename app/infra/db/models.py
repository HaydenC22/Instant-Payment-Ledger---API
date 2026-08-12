import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, func
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
    # payment_id / idempotency_key_id references are added once those tables exist (M2, M3).
    payment_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    entry_type: Mapped[str] = mapped_column(String(30))
    idempotency_key_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
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


# Payment, idempotency-key, FX, webhook and reconciliation tables are added in later
# milestones (M2-M6) as ORM models here, mirroring the schema in docs/architecture.md.
