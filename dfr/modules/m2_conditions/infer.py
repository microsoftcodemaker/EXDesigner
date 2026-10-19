"""Infer L and Cout (and ESR_eq, DCR) from the BOM through confirmed roles (PRD 3.2, OPC-12).

- L = value_si of the part with role ``inductor``; DCR from its ratings. More than one part
  in that role is an error until the user picks one (coupled/parallel inductors: v1).
- Cout = sum of nominal capacitances of ``output_cap`` parts. ESR_eq = parallel combination
  of their ESR ratings; missing ESRs are skipped with a diagnostic.
- A role part with a missing value blocks the template with a diagnostic naming the part.
Every inferred value records provenance ``bom`` and its contributing refdes; a user override
(provenance ``user``) wins and is marked "overrides BOM".
"""

from __future__ import annotations

from collections.abc import Mapping

from dfr.core.contracts import InferredValue, InferredValues, Part, RoleMap
from dfr.core.diagnostics import DiagnosticSink

MODULE_ID = "m2_conditions"


def infer_passives(  # noqa: PLR0912 - one branch per inference rule
    parts: list[Part],
    roles: RoleMap,
    *,
    overrides: Mapping[str, float] | None = None,
    sink: DiagnosticSink | None = None,
) -> InferredValues:
    sink = sink if sink is not None else DiagnosticSink(MODULE_ID)
    by_ref = {p.refdes: p for p in parts}
    out: dict[str, InferredValue] = {}

    inductors = roles.parts_with_role("inductor")
    if len(inductors) == 1:
        L = by_ref.get(inductors[0])
        if L is None or L.value_si is None:
            sink.error(
                "INFER_L_MISSING",
                f"{inductors[0]}: inductance value missing; enter it manually",
                part_id=L.id if L else None,
            )
        else:
            out["L"] = InferredValue(
                name="L", value=L.value_si, unit="H", contributing_refdes=(L.refdes,)
            )
            dcr = L.ratings.get("dcr")
            if dcr is not None:
                out["dcr"] = InferredValue(
                    name="dcr",
                    value=dcr.value,
                    unit="ohm",
                    contributing_refdes=(L.refdes,),
                    note=f"rating {dcr.provenance.value}",
                )
            else:
                sink.info(
                    "INFER_DCR_MISSING",
                    f"{L.refdes}: no DCR rating; inductor copper loss not computed",
                    part_id=L.id,
                )
    elif len(inductors) > 1:
        sink.error(
            "INFER_L_AMBIGUOUS",
            f"several parts have role inductor ({', '.join(inductors)}); "
            "pick one in Circuit Review (coupled/parallel inductors arrive in v1)",
        )
    else:
        sink.error("INFER_L_NO_ROLE", "no part has role inductor")

    caps = [by_ref[r] for r in roles.parts_with_role("output_cap") if r in by_ref]
    valued = [c for c in caps if c.value_si is not None]
    for c in caps:
        if c.value_si is None:
            sink.error(
                "INFER_COUT_MISSING",
                f"{c.refdes}: capacitance missing; enter it manually",
                part_id=c.id,
            )
    if valued:
        out["cout"] = InferredValue(
            name="cout",
            value=sum(c.value_si or 0.0 for c in valued),
            unit="F",
            contributing_refdes=tuple(c.refdes for c in valued),
            note="nominal sum; MLCC DC-bias derating arrives with LIF-02",
        )
        esrs = [(c.refdes, c.ratings.get("esr")) for c in valued]
        known = [(r, e.value) for r, e in esrs if e is not None and e.value > 0]
        if known:
            esr_eq = 1.0 / sum(1.0 / v for _, v in known)
            note = (
                None
                if len(known) == len(valued)
                else "some ESR values missing; parallel of the known ones"
            )
            if note:
                sink.warning(
                    "INFER_ESR_PARTIAL", f"ESR known for {len(known)}/{len(valued)} output caps"
                )
            out["esr_eq"] = InferredValue(
                name="esr_eq",
                value=esr_eq,
                unit="ohm",
                contributing_refdes=tuple(r for r, _ in known),
                note=note,
            )
        else:
            sink.info(
                "INFER_ESR_MISSING", "no ESR ratings on output caps; ripple voltage uses ESR = 0"
            )
    elif caps:
        pass  # already reported per part
    else:
        sink.error("INFER_COUT_NO_ROLE", "no part has role output_cap")

    for name, value in (overrides or {}).items():
        unit = (
            out[name].unit
            if name in out
            else {"L": "H", "cout": "F", "esr_eq": "ohm", "dcr": "ohm"}.get(name, "")
        )
        out[name] = InferredValue(
            name=name,
            value=value,
            unit=unit,
            provenance="user",
            contributing_refdes=(),
            note="overrides BOM",
        )
    return InferredValues(values=out)
