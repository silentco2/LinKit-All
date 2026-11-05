"""run reason code and stages

Revision ID: a6d4f8b0c235
Revises: f5c3e7a9b124
Create Date: 2026-11-01 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6d4f8b0c235"
down_revision: str | None = "f5c3e7a9b124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table(
        "runs"
    ) as batch:  # old runs keep NULL / {} / []: kind falls back to stats
        batch.add_column(sa.Column("reason_code", sa.String(length=48), nullable=True))
        batch.add_column(sa.Column("reason_params", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("stages", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("stages")
        batch.drop_column("reason_params")
        batch.drop_column("reason_code")
