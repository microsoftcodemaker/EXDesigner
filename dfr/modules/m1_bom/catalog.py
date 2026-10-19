"""Rating lookup: local part catalog (user-entered, by MPN/LibRef) then seed class defaults.

Order per PRD 3.1: catalog match -> seed defaults -> optional API (not implemented, off).
Each rating records where it came from. The catalog table is module-owned
(``m1_part_catalog``, branch ``m1_bom``).
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from dfr.core.contracts import PartClass, Rating, RatingProvenance
from dfr.core.db.base import Base
from dfr.core.db.types import UtcDateTime
from dfr.core.ports import Clock

DATA_DIR = Path(__file__).parent / "data"


class PartCatalogRow(Base):
    __tablename__ = "m1_part_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mpn: Mapped[str | None] = mapped_column(String(100), index=True)
    libref: Mapped[str | None] = mapped_column(String(100), index=True)
    footprint: Mapped[str | None] = mapped_column(String(100))
    part_class: Mapped[str] = mapped_column("class", String(30), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(50))
    ratings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    pinmap_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="user")
    dataset: Mapped[str] = mapped_column(String(100), nullable=False, default="user", index=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class CatalogImportRow(Base):
    """One imported file; rows carry its dataset name so the set can be replaced or deleted."""

    __tablename__ = "m1_catalog_import"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    fmt: Mapped[str] = mapped_column(String(10), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    imported_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class CatalogRepo:
    def __init__(self, session: Session, clock: Clock) -> None:
        self.s = session
        self.clock = clock

    def upsert(
        self,
        *,
        mpn: str | None,
        libref: str | None = None,
        footprint: str | None = None,
        part_class: PartClass,
        subtype: str | None = None,
        ratings: dict[str, Rating] | None = None,
        pinmap: dict[str, str] | None = None,
        source: str = "user",
        dataset: str = "user",
    ) -> PartCatalogRow:
        row = self.find(mpn=mpn, libref=libref, footprint=footprint)
        if row is None:
            row = PartCatalogRow(
                mpn=mpn, libref=libref, footprint=footprint, part_class=part_class.value
            )
            self.s.add(row)
        row.dataset = dataset
        row.part_class = part_class.value
        row.subtype = subtype
        if ratings is not None:
            row.ratings_json = json.dumps(
                {k: r.model_dump(mode="json") for k, r in ratings.items()}, sort_keys=True
            )
        if pinmap is not None:
            row.pinmap_json = json.dumps(pinmap, sort_keys=True)
        row.source = source
        row.updated_at = self.clock.now()
        self.s.flush()
        return row

    def find(
        self, *, mpn: str | None, libref: str | None = None, footprint: str | None = None
    ) -> PartCatalogRow | None:
        if mpn:
            row = self.s.scalar(select(PartCatalogRow).where(PartCatalogRow.mpn == mpn))
            if row is not None:
                return row
        if libref:
            stmt = select(PartCatalogRow).where(PartCatalogRow.libref == libref)
            if footprint:
                stmt = stmt.where(PartCatalogRow.footprint == footprint)
            return self.s.scalar(stmt)
        return None

    def all_rows(self, dataset: str | None = None) -> list[PartCatalogRow]:
        stmt = select(PartCatalogRow).order_by(PartCatalogRow.mpn, PartCatalogRow.libref)
        if dataset is not None:
            stmt = stmt.where(PartCatalogRow.dataset == dataset)
        return list(self.s.scalars(stmt))

    def delete_dataset(self, dataset: str) -> int:
        rows = self.all_rows(dataset)
        for r in rows:
            self.s.delete(r)
        imp = self.s.scalar(select(CatalogImportRow).where(CatalogImportRow.dataset == dataset))
        if imp is not None:
            self.s.delete(imp)
        self.s.flush()
        return len(rows)

    def datasets(self) -> list[CatalogImportRow]:
        return list(self.s.scalars(select(CatalogImportRow).order_by(CatalogImportRow.dataset)))

    def record_import(
        self, *, dataset: str, filename: str, fmt: str, sha256: str, entries: int, description: str
    ) -> CatalogImportRow:
        row = self.s.scalar(select(CatalogImportRow).where(CatalogImportRow.dataset == dataset))
        if row is None:
            row = CatalogImportRow(dataset=dataset, filename=filename, fmt=fmt, sha256=sha256)
            self.s.add(row)
        row.filename, row.fmt, row.sha256 = filename, fmt, sha256
        row.entries, row.description = entries, description
        row.imported_at = self.clock.now()
        self.s.flush()
        return row

    def ratings_for(self, row: PartCatalogRow) -> dict[str, Rating]:
        data: dict[str, Any] = json.loads(row.ratings_json)
        return {k: Rating.model_validate(v) for k, v in data.items()}

    def pinmap_for(self, row: PartCatalogRow) -> dict[str, str]:
        data: dict[str, str] = json.loads(row.pinmap_json)
        return data


@lru_cache(maxsize=1)
def _class_defaults() -> dict[str, Any]:
    with (DATA_DIR / "class_defaults.yaml").open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    defaults: dict[str, Any] = data["defaults"]
    return defaults


def seed_ratings(part_class: PartClass, package: str | None) -> dict[str, Rating]:
    """Generic class defaults, package-specific first then '*'. Provenance ``seed``."""
    table = _class_defaults().get(part_class.value, {})
    out: dict[str, Rating] = {}
    for key in ("*", (package or "").upper()):
        for name, spec in table.get(key, {}).items():
            out[name] = Rating(
                name=name,
                value=float(spec["value"]),
                unit=str(spec["unit"]),
                provenance=RatingProvenance.SEED,
                provenance_ref=str(spec.get("source", "seed")),
            )
    return out


def merge_ratings(*layers: dict[str, Rating]) -> dict[str, Rating]:
    """Later layers win. Call as merge_ratings(seed, description, catalog, user)."""
    merged: dict[str, Rating] = {}
    for layer in layers:
        merged.update(layer)
    return merged
