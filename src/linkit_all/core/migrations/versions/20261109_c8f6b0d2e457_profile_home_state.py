"""profile home state or governorate

Revision ID: c8f6b0d2e457
Revises: b7e5a9c1d346
Create Date: 2026-11-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8f6b0d2e457"
down_revision: str | None = "b7e5a9c1d346"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("profile") as batch:
        batch.add_column(sa.Column("home_state", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("profile") as batch:
        batch.drop_column("home_state")
