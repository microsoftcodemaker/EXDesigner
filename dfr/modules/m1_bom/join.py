"""Join the netlist to the BOM (PRD 3.1, NET-03, NET-05, NET-10).

Two paths:
- BOM has designators: match on refdes (case-insensitive, suffix-tolerant ``C1`` ~ ``C1_1``).
- BOM has no designators (.BomDoc): match the netlist component's comment (MPN) to the
  BOM template; every designator sharing an MPN receives the same ratings.

Netlist-only components become ``Part`` rows of class ``other`` (no stress checks). BOM-only
parts have no connectivity and are excluded from matching. DNP parts are pruned from the
graph before topology matching; their pins are treated as open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dfr.core.contracts import (
    ClassifiedBom,
    Diagnostic,
    JoinResult,
    NetlistGraph,
    Part,
    PartClass,
    RawPart,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.modules.m1_bom.classify import classify

_SUFFIX_RE = re.compile(r"[_\-.].*$")


@dataclass
class JoinedDesign:
    parts: list[Part]  # one per netlist component (+ BOM-only parts, which have no pins)
    graph: NetlistGraph
    join: JoinResult
    diagnostics: list[Diagnostic] = field(default_factory=list)


def join_netlist(graph: NetlistGraph, bom: ClassifiedBom) -> JoinedDesign:
    sink = DiagnosticSink("m1_bom")
    parts: list[Part] = []
    matched: dict[str, int] = {}
    netlist_only: list[str] = []

    if bom.templates_by_mpn and not bom.parts:
        parts, netlist_only = _join_by_mpn(graph, bom, sink)
        bom_only = sorted(set(bom.templates_by_mpn) - {p.mpn for p in parts if p.mpn})
    else:
        parts, netlist_only, bom_only = _join_by_refdes(graph, bom, sink)

    for i, p in enumerate(parts):
        matched[p.refdes] = i
    for refdes in netlist_only:
        sink.warning("JOIN_NETLIST_ONLY", f"{refdes}: in netlist but not in BOM; stored as 'other'")
    for key in bom_only:
        sink.warning("JOIN_BOM_ONLY", f"{key}: in BOM but not in netlist; no connectivity")

    return JoinedDesign(
        parts=parts,
        graph=graph,
        join=JoinResult(
            matched=matched,
            bom_only=list(bom_only),
            netlist_only=netlist_only,
            diagnostics=list(sink.items),
        ),
        diagnostics=list(sink.items),
    )


def prune_dnp(graph: NetlistGraph, parts: list[Part]) -> NetlistGraph:
    """Remove DNP parts' pins and components from the graph (NET-05)."""
    dnp = {p.refdes for p in parts if p.dnp}
    if not dnp:
        return graph
    return graph.model_copy(
        update={
            "components": [c for c in graph.components if c.refdes not in dnp],
            "pins": [p for p in graph.pins if p.refdes not in dnp],
        }
    )


# ----------------------------------------------------------------------------- strategies


def _join_by_mpn(
    graph: NetlistGraph, bom: ClassifiedBom, sink: DiagnosticSink
) -> tuple[list[Part], list[str]]:
    parts: list[Part] = []
    netlist_only: list[str] = []
    for comp in graph.components:
        template = bom.templates_by_mpn.get((comp.comment or "").strip())
        if template is None:
            netlist_only.append(comp.refdes)
            parts.append(_other_part(comp.refdes, comp.footprint, comp.comment))
            continue
        parts.append(
            template.model_copy(
                update={
                    "refdes": comp.refdes,
                    "package": template.package or comp.footprint,
                    "libref": template.libref or comp.footprint,
                }
            )
        )
        if template.class_confidence < 0.9:
            # A refdes is now known: re-run classification with the prefix for a better score.
            better = classify(
                RawPart(refdes=comp.refdes, description=template.description, mpn=template.mpn)
            )
            if (
                better.part_class is template.part_class
                and better.confidence > template.class_confidence
            ):
                parts[-1] = parts[-1].model_copy(update={"class_confidence": better.confidence})
            elif better.part_class is not template.part_class:
                sink.warning(
                    "JOIN_CLASS_CONFLICT",
                    f"{comp.refdes}: prefix suggests {better.part_class.value}, "
                    f"BOM description gave {template.part_class.value}",
                )
    return parts, netlist_only


def _join_by_refdes(
    graph: NetlistGraph, bom: ClassifiedBom, sink: DiagnosticSink
) -> tuple[list[Part], list[str], list[str]]:
    by_key = {_key(p.refdes): p for p in bom.parts}
    parts: list[Part] = []
    netlist_only: list[str] = []
    used: set[str] = set()
    for comp in graph.components:
        key = _key(comp.refdes)
        part = by_key.get(key)
        if part is None:
            netlist_only.append(comp.refdes)
            parts.append(_other_part(comp.refdes, comp.footprint, comp.comment))
            continue
        used.add(key)
        if part.refdes != comp.refdes:
            sink.info(
                "JOIN_REFDES_NORMALISED", f"netlist {comp.refdes!r} matched BOM {part.refdes!r}"
            )
        parts.append(
            part.model_copy(
                update={"refdes": comp.refdes, "package": part.package or comp.footprint}
            )
        )
    bom_only = [p.refdes for p in bom.parts if _key(p.refdes) not in used]
    parts.extend(p for p in bom.parts if _key(p.refdes) not in used)
    return parts, netlist_only, bom_only


def _key(refdes: str) -> str:
    """Case-insensitive, suffix-tolerant key: 'c1_1' -> 'C1'."""
    return _SUFFIX_RE.sub("", refdes.strip().upper())


def _other_part(refdes: str, footprint: str | None, comment: str | None) -> Part:
    cls = classify(RawPart(refdes=refdes, footprint=footprint, mpn=comment))
    return Part(
        refdes=refdes,
        part_class=cls.part_class if cls.part_class is not PartClass.UNKNOWN else PartClass.OTHER,
        subtype=cls.subtype,
        package=footprint,
        mpn=comment,
        class_confidence=min(cls.confidence, 0.5),
    )
