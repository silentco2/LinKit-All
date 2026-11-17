"""job outcome after applying (no reply, rejected, interview, offer, ...)

Revision ID: d9a7c1e3f568
Revises: c8f6b0d2e457
Create Date: 2026-11-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9a7c1e3f568"
down_revision: str | None = "c8f6b0d2e457"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("outcome", sa.String(16), nullable=True))
        batch.add_column(sa.Column("outcome_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("outcome_at")
        batch.drop_column("outcome")
