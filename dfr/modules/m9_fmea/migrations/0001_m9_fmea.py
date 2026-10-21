"""m9_fmea: FMEA rows per run and user overrides per design version

Revision ID: 0001_m9_fmea
Revises:
Branch: m9_fmea
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from dfr.core.db.types import UtcDateTime

revision = "0001_m9_fmea"
down_revision = None
branch_labels = ("m9_fmea",)
depends_on = None


def _fk(col: str, target: str, table: str) -> sa.ForeignKey:
    ref = target.split(".", maxsplit=1)[0]
    return sa.ForeignKey(target, ondelete="CASCADE", name=f"fk_{table}_{col}_{ref}")


def upgrade() -> None:
    op.create_table(
        "m9_fmea_row",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id", sa.Integer(), _fk("run_id", "analysis_run.id", "m9_fmea_row"), nullable=False
        ),
        sa.Column(
            "part_id", sa.Integer(), _fk("part_id", "part.id", "m9_fmea_row"), nullable=False
        ),
        sa.Column("mode_id", sa.String(60), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("local_effect", sa.Text(), nullable=False),
        sa.Column("system_effect", sa.Text(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("detection", sa.Integer(), nullable=False),
        sa.Column("rpn", sa.Integer(), nullable=False),
        sa.Column("flags_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("occurrence_basis", sa.String(60), nullable=False, server_default=""),
        sa.Column("lambda_fit", sa.Float()),
        sa.Column("life_ratio", sa.Float()),
        sa.Column("note", sa.Text()),
    )
    op.create_index("ix_m9_fmea_row_run_id", "m9_fmea_row", ["run_id"])
    op.create_index("ix_m9_fmea_row_part_id", "m9_fmea_row", ["part_id"])
    op.create_table(
        "m9_fmea_override",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "design_version_id",
            sa.Integer(),
            _fk("design_version_id", "design_version.id", "m9_fmea_override"),
            nullable=False,
        ),
        sa.Column(
            "part_id", sa.Integer(), _fk("part_id", "part.id", "m9_fmea_override"), nullable=False
        ),
        sa.Column("mode_id", sa.String(60), nullable=False),
        sa.Column("severity", sa.Integer()),
        sa.Column("occurrence", sa.Integer()),
        sa.Column("detection", sa.Integer()),
        sa.Column("note", sa.Text()),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
    )
    op.create_index(
        "ix_m9_fmea_override_design_version_id", "m9_fmea_override", ["design_version_id"]
    )
    op.create_index("ix_m9_fmea_override_part_id", "m9_fmea_override", ["part_id"])


def downgrade() -> None:
    op.drop_index("ix_m9_fmea_override_part_id", table_name="m9_fmea_override")
    op.drop_index("ix_m9_fmea_override_design_version_id", table_name="m9_fmea_override")
    op.drop_table("m9_fmea_override")
    op.drop_index("ix_m9_fmea_row_part_id", table_name="m9_fmea_row")
    op.drop_index("ix_m9_fmea_row_run_id", table_name="m9_fmea_row")
    op.drop_table("m9_fmea_row")
