from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dfr.core.db.base import Base
from dfr.core.db.types import UtcDateTime


class AnalysisRunRow(Base):
    """Immutable once ``finished_at`` is set (DAT-01). Re-runs link via ``parent_run_id``."""

    __tablename__ = "analysis_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_version_id: Mapped[int] = mapped_column(
        ForeignKey("design_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="SET NULL")
    )
    tier_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ruleset_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ruleset_hash: Mapped[str | None] = mapped_column(String(64))
    model_set_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")

    diagnostics: Mapped[list[DiagnosticRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EffectiveStressRow(Base):
    """Snapshot of which stress_value row fed each (part, param, scenario) in a run."""

    __tablename__ = "effective_stress"
    __table_args__ = (UniqueConstraint("run_id", "part_id", "param", "scenario"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(ForeignKey("part.id", ondelete="CASCADE"), nullable=False)
    param: Mapped[str] = mapped_column(String(30), nullable=False)
    scenario: Mapped[str] = mapped_column(String(30), nullable=False)
    stress_value_id: Mapped[int] = mapped_column(
        ForeignKey("stress_value.id", ondelete="RESTRICT"), nullable=False
    )


class DiagnosticRow(Base):
    __tablename__ = "diagnostic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module: Mapped[str | None] = mapped_column(String(50))
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    part_id: Mapped[int | None] = mapped_column(ForeignKey("part.id", ondelete="SET NULL"))
    line_no: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped[AnalysisRunRow] = relationship(back_populates="diagnostics")
