"""job sightings

Revision ID: e4b2d6f8a013
Revises: d3a1c5e7f902
Create Date: 2026-10-19 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b2d6f8a013"
down_revision: str | None = "d3a1c5e7f902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_sightings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("seen_at", sa.DateTime(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "run_id"),
    )
    op.create_index("ix_job_sightings_job_id", "job_sightings", ["job_id"])
    # Existing jobs get one sighting at their first discovery, so history starts complete.
    op.execute(
        "INSERT INTO job_sightings (job_id, run_id, seen_at, url, source)"
        " SELECT id, run_id, created_at, url, source FROM jobs"
    )


def downgrade() -> None:
    op.drop_index("ix_job_sightings_job_id", table_name="job_sightings")
    op.drop_table("job_sightings")
