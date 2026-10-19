"""m1_bom: catalog datasets (re-importable, deletable sets)

Revision ID: 0002_m1_catalog_datasets
Revises: 0001_m1_bom
Branch: m1_bom
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from dfr.core.db.types import UtcDateTime

revision = "0002_m1_catalog_datasets"
down_revision = "0001_m1_bom"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("m1_part_catalog") as batch:
        batch.add_column(
            sa.Column("dataset", sa.String(100), nullable=False, server_default="user")
        )
        batch.create_index("ix_m1_part_catalog_dataset", ["dataset"])
    op.create_table(
        "m1_catalog_import",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset", sa.String(100), nullable=False, unique=True),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("fmt", sa.String(10), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("entries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("imported_at", UtcDateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("m1_catalog_import")
    with op.batch_alter_table("m1_part_catalog") as batch:
        batch.drop_index("ix_m1_part_catalog_dataset")
        batch.drop_column("dataset")
