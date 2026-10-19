"""Parts and ratings (PRD sections 3.1, 5.1)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dfr.core.contracts.v1.enums import PartClass, RatingProvenance


class RawPart(BaseModel):
    """One BOM row before classification. ``refdes`` is None for designator-less BOMs (.BomDoc)."""

    model_config = ConfigDict(frozen=True)

    refdes: str | None
    value: str | None = None
    description: str | None = None
    footprint: str | None = None
    mpn: str | None = None
    libref: str | None = None
    quantity: int = 1
    dnp: bool = False
    source_row: int | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class Rating(BaseModel):
    """A single rating field (e.g. ``v_rated``) with its provenance."""

    model_config = ConfigDict(frozen=True)

    name: str
    value: float
    unit: str
    provenance: RatingProvenance
    provenance_ref: str | None = None


class RatingSet(BaseModel):
    ratings: dict[str, Rating] = Field(default_factory=dict)

    def get(self, name: str) -> Rating | None:
        return self.ratings.get(name)


class Part(BaseModel):
    """A classified part. ``id`` is the database id once persisted (None before)."""

    model_config = ConfigDict(frozen=True)

    id: int | None = None
    refdes: str
    part_class: PartClass
    subtype: str | None = None
    value_si: float | None = None
    value_unit: str | None = None
    package: str | None = None
    mpn: str | None = None
    libref: str | None = None
    description: str | None = None
    dnp: bool = False
    class_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    ratings: RatingSet = Field(default_factory=RatingSet)
