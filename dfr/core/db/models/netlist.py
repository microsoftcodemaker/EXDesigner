from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from dfr.core.db.base import Base


class NetRow(Base):
    __tablename__ = "net"
    __table_args__ = (UniqueConstraint("design_version_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_version_id: Mapped[int] = mapped_column(
        ForeignKey("design_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    kind_provenance: Mapped[str] = mapped_column(String(10), nullable=False, default="auto")


class PinRow(Base):
    __tablename__ = "pin"
    __table_args__ = (UniqueConstraint("part_id", "pin_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    net_id: Mapped[int | None] = mapped_column(
        ForeignKey("net.id", ondelete="SET NULL"), index=True
    )
    pin_id: Mapped[str] = mapped_column(String(20), nullable=False)
    function: Mapped[str | None] = mapped_column(String(30))
    function_provenance: Mapped[str | None] = mapped_column(String(10))
    pintype: Mapped[str | None] = mapped_column(String(30))
