"""Missing-data report: which parts of a design have no catalog entry and which ratings the
active derating rules need but the part lacks. Combines M1 and M5 through registry services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from dfr.core.contracts import Part, PartClass
from dfr.core.db.repos import PartRepo
from dfr.core.registry import DiscoveryResult

# Classes whose stress is never checked; no catalog data needed.
PASSIVE_INFO_CLASSES = {
    PartClass.CONNECTOR,
    PartClass.TEST_POINT,
    PartClass.OTHER,
    PartClass.SWITCH,
    PartClass.CRYSTAL,
}


@dataclass
class MissingRow:
    refdes: str
    mpn: str | None
    part_class: str
    subtype: str | None
    in_catalog: bool
    missing_ratings: list[str] = field(default_factory=list)
    needs_pinout: bool = False


def missing_data(
    session: Session,
    registry: DiscoveryResult,
    design_version_id: int,
    *,
    ruleset_id: str = "generic_conservative",
) -> list[MissingRow]:
    parts = PartRepo(session).for_version(design_version_id, include_dnp=False)
    needed_by_rule = _ratings_needed(registry, ruleset_id)
    catalog_keys = _catalog_keys(session, registry)
    rows: list[MissingRow] = []
    for p in parts:
        if p.part_class in PASSIVE_INFO_CLASSES:
            continue
        needed = needed_by_rule.get(
            (p.part_class.value, p.subtype), needed_by_rule.get((p.part_class.value, None), set())
        )
        missing = sorted(n for n in needed if p.ratings.get(n) is None)
        in_cat = (p.mpn in catalog_keys) if p.mpn else (f"{p.libref}@{p.package}" in catalog_keys)
        needs_pinout = p.part_class in (
            PartClass.TRANSISTOR,
            PartClass.DIODE,
            PartClass.IC,
        ) and not _has_pinmap(session, registry, p)
        if missing or needs_pinout:
            rows.append(
                MissingRow(
                    p.refdes, p.mpn, p.part_class.value, p.subtype, in_cat, missing, needs_pinout
                )
            )
    return rows


def _ratings_needed(
    registry: DiscoveryResult, ruleset_id: str
) -> dict[tuple[str, str | None], set[str]]:
    out: dict[tuple[str, str | None], set[str]] = {}
    if not registry.has_service("load_ruleset"):
        return out
    rs = registry.service("load_ruleset")(ruleset_id)
    if rs is None:
        return out
    for rule in rs.rules:
        out.setdefault((rule.part_class, rule.subtype), set()).add(rule.rating)
        if rule.curve:
            out[(rule.part_class, rule.subtype)].update(rule.curve)
    # subtype-specific sets inherit the generic ones
    for (cls, sub), names in list(out.items()):
        if sub is not None:
            names.update(out.get((cls, None), set()))
    return out


def _catalog_keys(session: Session, registry: DiscoveryResult) -> set[str]:
    if not registry.has_service("catalog.rows"):
        return set()
    from dfr.core.ports import SystemClock  # noqa: PLC0415

    keys: set[str] = set()
    for row in registry.service("catalog.rows")(session, SystemClock()):
        if row.mpn:
            keys.add(row.mpn)
        if row.libref:
            keys.add(f"{row.libref}@{row.footprint or ''}")
    return keys


def _has_pinmap(session: Session, registry: DiscoveryResult, part: Part) -> bool:
    if not registry.has_service("catalog.rows"):
        return False
    from dfr.core.ports import SystemClock  # noqa: PLC0415

    for row in registry.service("catalog.rows")(session, SystemClock()):
        if (part.mpn and row.mpn == part.mpn) or (not part.mpn and row.libref == part.libref):
            return row.pinmap_json not in ("", "{}")
    return False


def format_missing(rows: list[MissingRow]) -> str:
    if not rows:
        return "catalog: every stressed part has the ratings its rules need and a known pinout"
    lines = [f"{'part':<5}{'mpn':<22}{'class/subtype':<26}{'catalog':<9}missing"]
    for r in rows:
        what: list[Any] = list(r.missing_ratings)
        if r.needs_pinout:
            what.append("pinout")
        lines.append(
            f"{r.refdes:<5}{(r.mpn or '-')[:21]:<22}{(r.part_class + '/' + (r.subtype or '-')):<26}"
            f"{'yes' if r.in_catalog else 'no':<9}{', '.join(what) or '-'}"
        )
    return "\n".join(lines)
