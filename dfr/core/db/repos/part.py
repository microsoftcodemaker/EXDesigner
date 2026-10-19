from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from dfr.core.contracts.v1.enums import PartClass, RatingProvenance
from dfr.core.contracts.v1.part import Part, Rating, RatingSet
from dfr.core.db.models import PartRow, RatingRow


def _to_contract(row: PartRow) -> Part:
    ratings = {
        r.name: Rating(
            name=r.name,
            value=r.value,
            unit=r.unit,
            provenance=RatingProvenance(r.provenance),
            provenance_ref=r.provenance_ref,
        )
        for r in row.ratings
    }
    return Part(
        id=row.id,
        refdes=row.refdes,
        part_class=PartClass(row.part_class),
        subtype=row.subtype,
        value_si=row.value_si,
        value_unit=row.value_unit,
        package=row.package,
        mpn=row.mpn,
        libref=row.libref,
        description=row.description,
        dnp=row.dnp,
        class_confidence=row.class_confidence,
        ratings=RatingSet(ratings=ratings),
    )


class PartRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add(self, design_version_id: int, part: Part) -> Part:
        row = PartRow(
            design_version_id=design_version_id,
            refdes=part.refdes,
            part_class=part.part_class.value,
            subtype=part.subtype,
            value_si=part.value_si,
            value_unit=part.value_unit,
            package=part.package,
            mpn=part.mpn,
            libref=part.libref,
            description=part.description,
            dnp=part.dnp,
            class_confidence=part.class_confidence,
        )
        row.ratings = [
            RatingRow(
                name=r.name,
                value=r.value,
                unit=r.unit,
                provenance=r.provenance.value,
                provenance_ref=r.provenance_ref,
            )
            for r in part.ratings.ratings.values()
        ]
        self.s.add(row)
        self.s.flush()
        return _to_contract(row)

    def add_many(self, design_version_id: int, parts: Iterable[Part]) -> list[Part]:
        return [self.add(design_version_id, p) for p in parts]

    def get(self, part_id: int) -> Part | None:
        row = self.s.get(PartRow, part_id, options=[selectinload(PartRow.ratings)])
        return None if row is None else _to_contract(row)

    def by_refdes(self, design_version_id: int, refdes: str) -> Part | None:
        stmt = (
            select(PartRow)
            .options(selectinload(PartRow.ratings))
            .where(PartRow.design_version_id == design_version_id, PartRow.refdes == refdes)
        )
        row = self.s.scalar(stmt)
        return None if row is None else _to_contract(row)

    def for_version(self, design_version_id: int, *, include_dnp: bool = True) -> list[Part]:
        stmt = (
            select(PartRow)
            .options(selectinload(PartRow.ratings))
            .where(PartRow.design_version_id == design_version_id)
            .order_by(PartRow.refdes)
        )
        if not include_dnp:
            stmt = stmt.where(PartRow.dnp.is_(False))
        return [_to_contract(r) for r in self.s.scalars(stmt)]

    def set_rating(self, part_id: int, rating: Rating) -> None:
        """Upsert one rating; provenance is recorded per field (BOM-07)."""
        part = self.s.get(PartRow, part_id, options=[selectinload(PartRow.ratings)])
        if part is None:
            msg = f"part {part_id} not found"
            raise LookupError(msg)
        row = next((r for r in part.ratings if r.name == rating.name), None)
        if row is None:
            row = RatingRow(name=rating.name)
            part.ratings.append(row)
        row.value = rating.value
        row.unit = rating.unit
        row.provenance = rating.provenance.value
        row.provenance_ref = rating.provenance_ref
        self.s.flush()

    def set_dnp(self, part_id: int, dnp: bool) -> None:
        row = self.s.get(PartRow, part_id)
        if row is not None:
            row.dnp = dnp
            self.s.flush()
