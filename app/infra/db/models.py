from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Ledger, payment, idempotency, FX, webhook and reconciliation tables are added in later
# milestones (M1-M6) as ORM models here, mirroring the schema in docs/architecture.md.
