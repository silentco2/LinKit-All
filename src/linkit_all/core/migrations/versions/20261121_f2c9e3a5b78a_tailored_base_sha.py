"""tailored CV: the fingerprint of the CV file it was made from (stale-PDF check on retry)

Revision ID: f2c9e3a5b78a
Revises: e1b8d2f4a679
Create Date: 2026-11-21 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2c9e3a5b78a"
down_revision: str | None = "e1b8d2f4a679"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tailored_cvs") as batch:
        batch.add_column(sa.Column("base_sha", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tailored_cvs") as batch:
        batch.drop_column("base_sha")
