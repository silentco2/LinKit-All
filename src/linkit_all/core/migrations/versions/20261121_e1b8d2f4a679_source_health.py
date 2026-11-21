"""source health: each source's last result, from runs and live checks (B2)

Revision ID: e1b8d2f4a679
Revises: d9a7c1e3f568
Create Date: 2026-11-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1b8d2f4a679"
down_revision: str | None = "d9a7c1e3f568"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_health",
        sa.Column("key", sa.String(512), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("via", sa.String(8), nullable=False),
        sa.Column("jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("zero_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ever_found", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("source_health")
