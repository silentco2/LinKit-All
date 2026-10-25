"""message codes

Revision ID: d3a1c5e7f902
Revises: b0a4d7e2c158
Create Date: 2026-10-18 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a1c5e7f902"
down_revision: str | None = "b0a4d7e2c158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("action_items", "job_events")


def upgrade() -> None:
    for table in TABLES:  # old rows keep NULL / {} and show their English message
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("code", sa.String(length=48), nullable=True))
            batch.add_column(sa.Column("params", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("params")
            batch.drop_column("code")
