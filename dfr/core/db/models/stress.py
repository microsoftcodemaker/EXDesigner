from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dfr.core.db.base import Base
from dfr.core.db.types import UtcDateTime


class StressValueRow(Base):
    """Immutable (OPC-03: provenance columns are NOT NULL). Rows are never updated or deleted."""

    __tablename__ = "stress_value"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    param: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    stat: Mapped[str] = mapped_column(String(10), nullable=False)
    scenario: Mapped[str] = mapped_column(String(30), nullable=False, default="nominal")
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    template_instance_id: Mapped[int | None] = mapped_column(Integer)
    import_id: Mapped[int | None] = mapped_column(Integer)
    prompt_id: Mapped[int | None] = mapped_column(
        ForeignKey("value_prompt.id", ondelete="SET NULL")
    )


class ValuePromptRow(Base):
    __tablename__ = "value_prompt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_version_id: Mapped[int] = mapped_column(
        ForeignKey("design_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int | None] = mapped_column(ForeignKey("part.id", ondelete="CASCADE"))
    param: Mapped[str] = mapped_column(String(30), nullable=False)
    stat: Mapped[str] = mapped_column(String(10), nullable=False)
    scenario: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    how_to_obtain: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(5), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    answered_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
