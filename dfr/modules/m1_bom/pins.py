"""Pin-function resolution (PRD 3.1, NET-06).

Two-terminal passives: pins are interchangeable (function ``terminal``). FETs, diodes and
ICs: the function comes from the netlist (``pinfunction``, when the format has it), then
the pin-map library (catalog ``pinmap_json`` keyed by MPN, or LibRef + footprint). If neither
knows the symbol the app does not guess: it returns a ``PinoutRequest`` and the part is
excluded from matching until the user answers. Answers are saved to the library so the
same part is asked once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dfr.core.contracts import (
    NetlistGraph,
    Part,
    PartClass,
    Pin,
    PinFunctionProvenance,
    PinoutRequest,
)
from dfr.modules.m1_bom.catalog import CatalogRepo

TWO_TERMINAL = {PartClass.RESISTOR, PartClass.CAPACITOR, PartClass.INDUCTOR, PartClass.FUSE}
NEEDS_PINOUT = {PartClass.TRANSISTOR, PartClass.DIODE, PartClass.IC}
PINOUT_CLASSES = TWO_TERMINAL | NEEDS_PINOUT


@dataclass
class PinResolution:
    pins: list[Pin]
    requests: list[PinoutRequest] = field(default_factory=list)
    unresolved_refdes: set[str] = field(default_factory=set)


def resolve_pin_functions(
    graph: NetlistGraph,
    parts: list[Part],
    catalog: CatalogRepo | None = None,
    *,
    inferred: dict[str, dict[str, str]] | None = None,
) -> PinResolution:
    """Fill ``Pin.function``/``function_provenance``; collect requests for unknown pinouts.

    ``inferred`` (refdes -> pin_id -> function) is prefill from M12's structural inference;
    it is attached to the request only, never applied (marked ``inferred``).
    """
    by_refdes = {p.refdes: p for p in parts}
    pins_by_part: dict[str, list[Pin]] = {}
    for pin in graph.pins:
        pins_by_part.setdefault(pin.refdes, []).append(pin)

    out: list[Pin] = []
    requests: list[PinoutRequest] = []
    unresolved: set[str] = set()

    for refdes, pins in pins_by_part.items():
        part = by_refdes.get(refdes)
        if part is None or part.part_class not in PINOUT_CLASSES:
            out.extend(pins)
            continue
        if part.part_class in TWO_TERMINAL and len(pins) <= 2:
            out.extend(_tag(pins, "terminal", PinFunctionProvenance.SEED))
            continue

        already = {p.pin_id: p for p in pins if p.function}
        if len(already) == len(pins):
            out.extend(pins)  # netlist supplied every function
            continue

        pinmap = _library_pinmap(part, catalog)
        if pinmap and all(p.pin_id in pinmap for p in pins):
            out.extend(
                p.model_copy(
                    update={
                        "function": pinmap[p.pin_id],
                        "function_provenance": PinFunctionProvenance.SEED,
                    }
                )
                if not p.function
                else p
                for p in pins
            )
            continue

        unresolved.add(refdes)
        out.extend(pins)
        prefill = dict((inferred or {}).get(refdes, {}))
        prefill.update(
            {pid: pinmap[pid] for pid in pinmap or {} if pid in {p.pin_id for p in pins}}
        )
        requests.append(
            PinoutRequest(
                refdes=refdes,
                mpn=part.mpn,
                libref=part.libref,
                footprint=part.package,
                pin_ids=tuple(sorted((p.pin_id for p in pins), key=_pin_sort)),
                inferred=prefill,
            )
        )
    return PinResolution(pins=out, requests=requests, unresolved_refdes=unresolved)


def apply_user_pinout(
    resolution: PinResolution,
    refdes: str,
    pinout: dict[str, str],
    catalog: CatalogRepo | None,
    part: Part,
) -> PinResolution:
    """Apply a confirmed pinout, save it to the library, drop the request."""
    pins = [
        p.model_copy(
            update={
                "function": pinout.get(p.pin_id, p.function),
                "function_provenance": PinFunctionProvenance.USER,
            }
        )
        if p.refdes == refdes
        else p
        for p in resolution.pins
    ]
    if catalog is not None:
        catalog.upsert(
            mpn=part.mpn,
            libref=part.libref,
            footprint=part.package,
            part_class=part.part_class,
            subtype=part.subtype,
            pinmap=pinout,
            source="user",
        )
    return PinResolution(
        pins=pins,
        requests=[r for r in resolution.requests if r.refdes != refdes],
        unresolved_refdes=resolution.unresolved_refdes - {refdes},
    )


def _library_pinmap(part: Part, catalog: CatalogRepo | None) -> dict[str, str]:
    if catalog is None:
        return {}
    row = catalog.find(mpn=part.mpn, libref=part.libref, footprint=part.package)
    return catalog.pinmap_for(row) if row is not None else {}


def _tag(pins: list[Pin], function: str, prov: PinFunctionProvenance) -> list[Pin]:
    return [p.model_copy(update={"function": function, "function_provenance": prov}) for p in pins]


def _pin_sort(pin_id: str) -> tuple[int, str]:
    return (int(pin_id), "") if pin_id.isdigit() else (10**6, pin_id)
