"""m6_thermal: thermal result table

Revision ID: 0001_m6_thermal
Revises:
Branch: m6_thermal
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_m6_thermal"
down_revision = None
branch_labels = ("m6_thermal",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m6_thermal_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey(
                "analysis_run.id",
                ondelete="CASCADE",
                name="fk_m6_thermal_result_run_id_analysis_run",
            ),
            nullable=False,
        ),
        sa.Column(
            "part_id",
            sa.Integer(),
            sa.ForeignKey("part.id", ondelete="CASCADE", name="fk_m6_thermal_result_part_id_part"),
            nullable=False,
        ),
        sa.Column("scenario", sa.String(30), nullable=False),
        sa.Column("tj", sa.Float(), nullable=False),
        sa.Column("tc", sa.Float()),
        sa.Column("p_total", sa.Float(), nullable=False),
        sa.Column("delta_tj_cycles_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("runaway_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_m6_thermal_result_run_id", "m6_thermal_result", ["run_id"])
    op.create_index("ix_m6_thermal_result_part_id", "m6_thermal_result", ["part_id"])


def downgrade() -> None:
    op.drop_index("ix_m6_thermal_result_part_id", table_name="m6_thermal_result")
    op.drop_index("ix_m6_thermal_result_run_id", table_name="m6_thermal_result")
    op.drop_table("m6_thermal_result")
