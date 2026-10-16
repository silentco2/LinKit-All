"""vault

Revision ID: 5a3e8b1c9d20
Revises: cc7ce03e7850
Create Date: 2026-10-16 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5a3e8b1c9d20"
down_revision: str | None = "cc7ce03e7850"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vault_meta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("salt", sa.LargeBinary(), nullable=False),
        sa.Column("kdf", sa.JSON(), nullable=False),
        sa.Column("check_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("check_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vault_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("site", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "site", "username"),
    )


def downgrade() -> None:
    op.drop_table("vault_entries")
    op.drop_table("vault_meta")
