"""cv source format and approval

Revision ID: 7c4d2e9f1a63
Revises: 5a3e8b1c9d20
Create Date: 2026-10-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c4d2e9f1a63"
down_revision: str | None = "5a3e8b1c9d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("profile") as batch:
        batch.add_column(
            sa.Column("cv_source_format", sa.Text(), nullable=False, server_default="docx")
        )
        batch.add_column(
            sa.Column("cv_approved", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("profile") as batch:
        batch.drop_column("cv_approved")
        batch.drop_column("cv_source_format")
