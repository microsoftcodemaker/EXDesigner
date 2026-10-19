"""example: note table

Revision ID: 0001_example
Revises:
Branch: example (label must equal the module id; core is always upgraded first)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_example"
down_revision = None
branch_labels = ("example",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "example_note",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "part_id",
            sa.Integer(),
            sa.ForeignKey("part.id", ondelete="CASCADE", name="fk_example_note_part_id_part"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("example_note")
