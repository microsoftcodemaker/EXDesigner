"""m3_triage: refinement items and waivers

Revision ID: 0001_m3_triage
Revises:
Branch: m3_triage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from dfr.core.db.types import UtcDateTime

revision = "0001_m3_triage"
down_revision = None
branch_labels = ("m3_triage",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m3_refinement_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey(
                "analysis_run.id",
                ondelete="CASCADE",
                name="fk_m3_refinement_item_run_id_analysis_run",
            ),
            nullable=False,
        ),
        sa.Column(
            "part_id",
            sa.Integer(),
            sa.ForeignKey("part.id", ondelete="CASCADE", name="fk_m3_refinement_item_part_id_part"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("flags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("params_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("scenarios_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("waiver_reason", sa.Text()),
    )
    op.create_index("ix_m3_refinement_item_run_id", "m3_refinement_item", ["run_id"])
    op.create_index("ix_m3_refinement_item_part_id", "m3_refinement_item", ["part_id"])
    op.create_table(
        "m3_waiver",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "design_version_id",
            sa.Integer(),
            sa.ForeignKey(
                "design_version.id",
                ondelete="CASCADE",
                name="fk_m3_waiver_design_version_id_design_version",
            ),
            nullable=False,
        ),
        sa.Column(
            "part_id",
            sa.Integer(),
            sa.ForeignKey("part.id", ondelete="CASCADE", name="fk_m3_waiver_part_id_part"),
            nullable=False,
        ),
        sa.Column("flag", sa.String(60), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
    )
    op.create_index("ix_m3_waiver_design_version_id", "m3_waiver", ["design_version_id"])
    op.create_index("ix_m3_waiver_part_id", "m3_waiver", ["part_id"])


def downgrade() -> None:
    op.drop_index("ix_m3_waiver_part_id", table_name="m3_waiver")
    op.drop_index("ix_m3_waiver_design_version_id", table_name="m3_waiver")
    op.drop_table("m3_waiver")
    op.drop_index("ix_m3_refinement_item_part_id", table_name="m3_refinement_item")
    op.drop_index("ix_m3_refinement_item_run_id", table_name="m3_refinement_item")
    op.drop_table("m3_refinement_item")
