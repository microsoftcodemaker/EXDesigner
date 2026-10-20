"""m8_failure_rate: failure-rate result table

Revision ID: 0001_m8_failure_rate
Revises:
Branch: m8_failure_rate
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_m8_failure_rate"
down_revision = None
branch_labels = ("m8_failure_rate",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m8_failure_rate_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey(
                "analysis_run.id",
                ondelete="CASCADE",
                name="fk_m8_failure_rate_result_run_id_analysis_run",
            ),
            nullable=False,
        ),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("table_id", sa.String(40)),
        sa.Column("confidence", sa.String(10)),
        sa.Column("system_lambda_fit", sa.Float()),
        sa.Column("system_mtbf_h", sa.Float()),
        sa.Column("system_mttf_h", sa.Float()),
        sa.Column("b10_h", sa.Float()),
        sa.Column("per_part_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("curve_json", sa.Text()),
        sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("excluded_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_m8_failure_rate_result_run_id", "m8_failure_rate_result", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_m8_failure_rate_result_run_id", table_name="m8_failure_rate_result")
    op.drop_table("m8_failure_rate_result")
