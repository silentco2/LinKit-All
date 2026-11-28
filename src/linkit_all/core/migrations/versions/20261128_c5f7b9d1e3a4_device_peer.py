"""devices.peer: the phone's iroh id, so a token only works from the phone it was given to

Revision ID: c5f7b9d1e3a4
Revises: b4e6a8c0d2f3
Create Date: 2026-11-28 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f7b9d1e3a4"
down_revision: str | None = "b4e6a8c0d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("peer", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("peer")
