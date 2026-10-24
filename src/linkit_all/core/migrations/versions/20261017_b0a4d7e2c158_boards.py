"""boards

Revision ID: b0a4d7e2c158
Revises: 7c4d2e9f1a63
Create Date: 2026-10-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0a4d7e2c158"
down_revision: str | None = "7c4d2e9f1a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "boards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ats", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(), nullable=False),
        sa.Column("last_crawled_at", sa.DateTime(), nullable=True),
        sa.Column("last_jobs", sa.Integer(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ats", "slug"),
    )
    op.create_index(op.f("ix_boards_active"), "boards", ["active"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_boards_active"), table_name="boards")
    op.drop_table("boards")
