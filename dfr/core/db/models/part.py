from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dfr.core.db.base import Base


class PartRow(Base):
    __tablename__ = "part"
    __table_args__ = (UniqueConstraint("design_version_id", "refdes"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_version_id: Mapped[int] = mapped_column(
        ForeignKey("design_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refdes: Mapped[str] = mapped_column(String(50), nullable=False)
    part_class: Mapped[str] = mapped_column("class", String(30), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(50))
    value_si: Mapped[float | None] = mapped_column(Float)
    value_unit: Mapped[str | None] = mapped_column(String(20))
    package: Mapped[str | None] = mapped_column(String(100))
    mpn: Mapped[str | None] = mapped_column(String(100), index=True)
    libref: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    dnp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    class_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    ratings: Mapped[list[RatingRow]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )


class RatingRow(Base):
    __tablename__ = "rating"
    __table_args__ = (UniqueConstraint("part_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    provenance: Mapped[str] = mapped_column(String(30), nullable=False)
    provenance_ref: Mapped[str | None] = mapped_column(Text)

    part: Mapped[PartRow] = relationship(back_populates="ratings")
