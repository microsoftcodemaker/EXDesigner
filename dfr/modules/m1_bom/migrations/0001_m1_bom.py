"""m1_bom: part catalog

Revision ID: 0001_m1_bom
Revises:
Branch: m1_bom
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from dfr.core.db.types import UtcDateTime

revision = "0001_m1_bom"
down_revision = None
branch_labels = ("m1_bom",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m1_part_catalog",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mpn", sa.String(100)),
        sa.Column("libref", sa.String(100)),
        sa.Column("footprint", sa.String(100)),
        sa.Column("class", sa.String(30), nullable=False),
        sa.Column("subtype", sa.String(50)),
        sa.Column("ratings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("pinmap_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source", sa.String(30), nullable=False, server_default="user"),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
    )
    op.create_index("ix_m1_part_catalog_mpn", "m1_part_catalog", ["mpn"])
    op.create_index("ix_m1_part_catalog_libref", "m1_part_catalog", ["libref"])


def downgrade() -> None:
    op.drop_index("ix_m1_part_catalog_libref", table_name="m1_part_catalog")
    op.drop_index("ix_m1_part_catalog_mpn", table_name="m1_part_catalog")
    op.drop_table("m1_part_catalog")
