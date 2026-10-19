"""M1 import service: bytes -> classified parts with ratings and provenance."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from dfr.core.contracts import (
    BomImportResult,
    ClassifiedBom,
    Part,
    PartClass,
    Rating,
    RatingSet,
    RawPart,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.ports import Clock, SystemClock
from dfr.core.values import parse_value
from dfr.modules.m1_bom.catalog import CatalogRepo, merge_ratings, seed_ratings
from dfr.modules.m1_bom.classify import REVIEW_THRESHOLD, Classification, classify
from dfr.modules.m1_bom.description import DescriptionFacts, parse_description
from dfr.modules.m1_bom.readers import BomReader, default_readers, pick_reader

MODULE_ID = "m1_bom"
_DEFAULT_UNIT = {
    PartClass.CAPACITOR: "F",
    PartClass.INDUCTOR: "H",
    PartClass.RESISTOR: "ohm",
}


def read_bom(
    data: bytes, name: str, *, fmt: str | None = None, readers: Sequence[BomReader] | None = None
) -> BomImportResult:
    readers = readers or default_readers()
    reader = pick_reader(data, name, readers, fmt)
    if reader is None:
        sink = DiagnosticSink(MODULE_ID)
        sink.error("BOM_UNKNOWN_FORMAT", f"no reader recognises {name!r}")
        return BomImportResult(
            raw_parts=[],
            source_format="unknown",
            source_hash="",
            source_name=name,
            diagnostics=list(sink.items),
        )
    return reader.read(data, name)


def classify_bom(
    imported: BomImportResult, *, session: Session | None = None, clock: Clock | None = None
) -> ClassifiedBom:
    """Classify rows, parse description facts, layer ratings: seed < description < catalog."""
    sink = DiagnosticSink(MODULE_ID)
    sink.extend(imported.diagnostics)
    catalog = CatalogRepo(session, clock or SystemClock()) if session is not None else None
    out = ClassifiedBom()
    seen_refdes: dict[str, int] = {}

    for raw in imported.raw_parts:
        key = raw.refdes or raw.mpn or f"row{raw.source_row}"
        if raw.refdes and raw.refdes in seen_refdes:
            sink.error(
                "BOM_DUPLICATE_REFDES",
                f"refdes {raw.refdes!r} also on row {seen_refdes[raw.refdes]}",
                line_no=raw.source_row,
            )
            continue
        if raw.refdes:
            seen_refdes[raw.refdes] = raw.source_row or 0

        cls = classify(raw)
        _report_classification(cls, key, raw, out, sink)
        part = _build_part(raw, cls, catalog, sink, key)

        if raw.refdes:
            out.parts.append(part)
        elif raw.mpn:
            out.templates_by_mpn[raw.mpn] = part
        else:
            sink.error(
                "BOM_NO_KEY", "row has neither refdes nor MPN; skipped", line_no=raw.source_row
            )

    out.diagnostics = list(sink.items)
    return out


def import_bom(
    data: bytes,
    name: str,
    *,
    fmt: str | None = None,
    session: Session | None = None,
    clock: Clock | None = None,
) -> tuple[BomImportResult, ClassifiedBom]:
    imported = read_bom(data, name, fmt=fmt)
    return imported, classify_bom(imported, session=session, clock=clock)


# ----------------------------------------------------------------------------- helpers


def _report_classification(
    cls: Classification, key: str, raw: RawPart, out: ClassifiedBom, sink: DiagnosticSink
) -> None:
    if cls.conflict:
        sink.warning("BOM_CLASS_CONFLICT", f"{key}: {cls.conflict}", line_no=raw.source_row)
    if cls.part_class is PartClass.UNKNOWN:
        sink.warning("BOM_CLASS_UNKNOWN", f"{key}: could not classify", line_no=raw.source_row)
    if cls.confidence < REVIEW_THRESHOLD:
        out.review_queue.append(key)
    if cls.topology_hints:
        out.topology_hints[key] = cls.topology_hints


def _build_part(
    raw: RawPart,
    cls: Classification,
    catalog: CatalogRepo | None,
    sink: DiagnosticSink,
    key: str,
) -> Part:
    facts = parse_description(raw.description, cls.part_class)
    value_si, value_unit = _value(raw, facts, cls.part_class, sink, key)
    package = raw.footprint or facts.package

    catalog_ratings: dict[str, Rating] = {}
    if catalog is not None:
        row = catalog.find(mpn=raw.mpn, libref=raw.libref, footprint=raw.footprint)
        if row is not None:
            catalog_ratings = catalog.ratings_for(row)
    ratings = merge_ratings(seed_ratings(cls.part_class, package), facts.ratings, catalog_ratings)

    attributes: dict[str, str] = {}
    if facts.dielectric:
        attributes["dielectric"] = facts.dielectric
    if facts.tolerance_pct is not None:
        attributes["tolerance_pct"] = f"{facts.tolerance_pct:g}"
    if cls.subtype in ("mosfet_n", "mosfet_p"):
        attributes["channel"] = cls.subtype[-1]

    return Part(
        refdes=raw.refdes or "",
        part_class=cls.part_class,
        subtype=cls.subtype,
        value_si=value_si,
        value_unit=value_unit,
        package=package,
        mpn=raw.mpn,
        libref=raw.libref,
        description=raw.description,
        dnp=raw.dnp,
        class_confidence=cls.confidence,
        ratings=RatingSet(ratings=ratings),
        attributes=attributes,
    )


def _value(
    raw: RawPart, facts: DescriptionFacts, part_class: PartClass, sink: DiagnosticSink, key: str
) -> tuple[float | None, str | None]:
    default_unit = _DEFAULT_UNIT.get(part_class)
    if raw.value:
        parsed = parse_value(raw.value, default_unit=default_unit)
        if parsed is not None:
            return parsed.magnitude, parsed.unit or default_unit
        sink.warning(
            "BOM_VALUE_UNPARSED",
            f"{key}: value {raw.value!r} not understood",
            line_no=raw.source_row,
        )
    if facts.value is not None:
        return facts.value.magnitude, facts.value.unit
    if default_unit is not None:
        sink.info(
            "BOM_VALUE_MISSING", f"{key}: no value for {part_class.value}", line_no=raw.source_row
        )
    return None, None
