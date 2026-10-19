"""BOM import results (PRD 3.1)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.contracts.v1.part import Part, RawPart


class BomImportResult(BaseModel):
    """Raw rows read from a BOM file plus provenance of the file itself."""

    raw_parts: list[RawPart] = Field(default_factory=list)
    source_format: str
    source_hash: str  # sha256 of the file bytes
    source_name: str | None = None
    has_designators: bool = True
    links: dict[str, list[str]] = Field(
        default_factory=dict
    )  # mpn -> datasheet URLs (never fetched)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ClassifiedBom(BaseModel):
    """Output of classification + rating lookup, ready to persist."""

    parts: list[Part] = Field(default_factory=list)  # BOMs with designators
    templates_by_mpn: dict[str, Part] = Field(default_factory=dict)  # designator-less BOMs
    review_queue: list[str] = Field(default_factory=list)  # refdes/mpn with confidence < threshold
    topology_hints: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # refdes/mpn -> hints
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @property
    def has_designators(self) -> bool:
        return bool(self.parts) or not self.templates_by_mpn
