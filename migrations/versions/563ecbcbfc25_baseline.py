"""baseline

Revision ID: 563ecbcbfc25
Revises:
Create Date: 2026-08-12 13:19:54.264847

"""

from collections.abc import Sequence

revision: str = "563ecbcbfc25"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
