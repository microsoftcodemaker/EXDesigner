"""m7_lifetime: lifetime result table

Revision ID: 0001_m7_lifetime
Revises:
Branch: m7_lifetime
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_m7_lifetime"
down_revision = None
branch_labels = ("m7_lifetime",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m7_lifetime_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey(
                "analysis_run.id",
                ondelete="CASCADE",
                name="fk_m7_lifetime_result_run_id_analysis_run",
            ),
            nullable=False,
        ),
        sa.Column(
            "part_id",
            sa.Integer(),
            sa.ForeignKey("part.id", ondelete="CASCADE", name="fk_m7_lifetime_result_part_id_part"),
            nullable=False,
        ),
        sa.Column("mechanism", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(60), nullable=False),
        sa.Column("life_hours", sa.Float()),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("input_stress_ids", sa.String(200), nullable=False, server_default=""),
    )
    op.create_index("ix_m7_lifetime_result_run_id", "m7_lifetime_result", ["run_id"])
    op.create_index("ix_m7_lifetime_result_part_id", "m7_lifetime_result", ["part_id"])


def downgrade() -> None:
    op.drop_index("ix_m7_lifetime_result_part_id", table_name="m7_lifetime_result")
    op.drop_index("ix_m7_lifetime_result_run_id", table_name="m7_lifetime_result")
    op.drop_table("m7_lifetime_result")
