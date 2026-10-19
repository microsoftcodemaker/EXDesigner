from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dfr.core.db.base import Base
from dfr.core.db.types import UtcDateTime


class StageRow(Base):
    __tablename__ = "stage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_version_id: Mapped[int] = mapped_column(
        ForeignKey("design_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pattern_id: Mapped[str] = mapped_column(String(100), nullable=False)
    pattern_version: Mapped[str] = mapped_column(String(30), nullable=False)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    netlist_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="proposed")

    rails: Mapped[list[RailRow]] = relationship(
        back_populates="stage", cascade="all, delete-orphan"
    )
    assignments: Mapped[list[RoleAssignmentRow]] = relationship(
        back_populates="stage", cascade="all, delete-orphan"
    )


class RailRow(Base):
    __tablename__ = "rail"
    __table_args__ = (UniqueConstraint("stage_id", "rail"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("stage.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rail: Mapped[str] = mapped_column(String(30), nullable=False)
    net_id: Mapped[int | None] = mapped_column(ForeignKey("net.id", ondelete="SET NULL"))
    net_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provenance: Mapped[str] = mapped_column(String(10), nullable=False, default="proposed")

    stage: Mapped[StageRow] = relationship(back_populates="rails")


class RoleAssignmentRow(Base):
    __tablename__ = "role_assignment"
    __table_args__ = (UniqueConstraint("stage_id", "part_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("stage.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    rail_id: Mapped[int | None] = mapped_column(ForeignKey("rail.id", ondelete="SET NULL"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provenance: Mapped[str] = mapped_column(String(10), nullable=False, default="proposed")
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    stage: Mapped[StageRow] = relationship(back_populates="assignments")
