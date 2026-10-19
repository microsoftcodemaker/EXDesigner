from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dfr.core.db.base import Base
from dfr.core.db.types import UtcDateTime


class Design(Base):
    __tablename__ = "design"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    topology_template: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    versions: Mapped[list[DesignVersion]] = relationship(
        back_populates="design", cascade="all, delete-orphan", order_by="DesignVersion.version_no"
    )


class DesignVersion(Base):
    __tablename__ = "design_version"
    __table_args__ = (UniqueConstraint("design_id", "version_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_id: Mapped[int] = mapped_column(
        ForeignKey("design.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    bom_hash: Mapped[str | None] = mapped_column(String(64))
    netlist_hash: Mapped[str | None] = mapped_column(String(64))
    netlist_format: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    design: Mapped[Design] = relationship(back_populates="versions")
