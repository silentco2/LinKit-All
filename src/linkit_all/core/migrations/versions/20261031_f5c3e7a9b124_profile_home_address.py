"""profile home address

Revision ID: f5c3e7a9b124
Revises: e4b2d6f8a013
Create Date: 2026-10-31 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5c3e7a9b124"
down_revision: str | None = "e4b2d6f8a013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("address", "postal_code", "home_city", "home_country")


def upgrade() -> None:
    with op.batch_alter_table("profile") as batch:
        for name in _COLUMNS:
            batch.add_column(sa.Column(name, sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("profile") as batch:
        for name in reversed(_COLUMNS):
            batch.drop_column(name)
