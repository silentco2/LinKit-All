"""answer bank scope: general, per role, per company

Revision ID: b7e5a9c1d346
Revises: a6d4f8b0c235
Create Date: 2026-11-08 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e5a9c1d346"
down_revision: str | None = "a6d4f8b0c235"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("answer_bank") as batch:
        batch.add_column(sa.Column("scope", sa.String(8), nullable=False, server_default="general"))
        batch.add_column(sa.Column("scope_name", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("answer_bank") as batch:
        batch.drop_column("scope_name")
        batch.drop_column("scope")
