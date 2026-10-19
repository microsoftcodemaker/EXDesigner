"""m5_derating: derating result table

Revision ID: 0001_m5_derating
Revises:
Branch: m5_derating
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_m5_derating"
down_revision = None
branch_labels = ("m5_derating",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m5_derating_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey(
                "analysis_run.id",
                ondelete="CASCADE",
                name="fk_m5_derating_result_run_id_analysis_run",
            ),
            nullable=False,
        ),
        sa.Column(
            "part_id",
            sa.Integer(),
            sa.ForeignKey("part.id", ondelete="CASCADE", name="fk_m5_derating_result_part_id_part"),
            nullable=False,
        ),
        sa.Column("param", sa.String(30), nullable=False),
        sa.Column("stress", sa.Float()),
        sa.Column("limit", sa.Float()),
        sa.Column("rating", sa.Float()),
        sa.Column("ratio", sa.Float()),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("margin", sa.Float()),
        sa.Column("rule_id", sa.String(50), nullable=False),
        sa.Column("stress_value_ids", sa.String(200), nullable=False, server_default=""),
    )
    op.create_index("ix_m5_derating_result_run_id", "m5_derating_result", ["run_id"])
    op.create_index("ix_m5_derating_result_part_id", "m5_derating_result", ["part_id"])


def downgrade() -> None:
    op.drop_index("ix_m5_derating_result_part_id", table_name="m5_derating_result")
    op.drop_index("ix_m5_derating_result_run_id", table_name="m5_derating_result")
    op.drop_table("m5_derating_result")
