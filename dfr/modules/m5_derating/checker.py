"""Derating checker (PRD 3.5, DER-01, DER-03, DER-04).

limit = factor * rating + offset. Resistor power uses the temperature curve:
    P_allowed = P_rated * min(1, (T_max - T_part) / (T_max - T_knee)) * factor
PASS: stress <= limit. WARN: limit < stress <= rating. FAIL: stress > rating.
Rating missing -> UNKNOWN, never PASS. Stress for a rule's param missing -> skipped with an
info diagnostic (the template did not produce it). The worst scenario is checked per param.
"""

from __future__ import annotations

from collections.abc import Mapping

from dfr.core.contracts import (
    DeratingResult,
    DeratingStatus,
    Part,
    StressKey,
    StressValue,
    ThermalResult,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.modules.m5_derating.ruleset import MODULE_ID, Rule, RuleSet

TJ_PARAM = "tj"


def evaluate_derating(
    parts: list[Part],
    effective: Mapping[StressKey, StressValue],
    ruleset: RuleSet,
    *,
    thermal: list[ThermalResult] | None = None,
    t_ambient: float | None = None,
    sink: DiagnosticSink | None = None,
) -> list[DeratingResult]:
    sink = sink if sink is not None else DiagnosticSink(MODULE_ID)
    tj_by_part = _worst_tj(thermal or [])
    results: list[DeratingResult] = []
    for part in parts:
        if part.id is None or part.dnp:
            continue
        rules = ruleset.for_part(part.part_class.value, part.subtype)
        by_param = _worst_stress_by_param(part.id, effective)
        for rule in rules:
            ids: tuple[int, ...] = ()
            if rule.param == TJ_PARAM:
                tj = tj_by_part.get(part.id)
                if tj is None:
                    continue
                stress_val = tj
            else:
                hit = by_param.get(rule.param)
                if hit is None:
                    continue
                stress_val = hit.value
                if hit.id is not None:
                    ids = (hit.id,)
            results.append(
                _check(part, rule, stress_val, ids, tj_by_part.get(part.id), t_ambient, sink)
            )
    return results


def _check(  # noqa: PLR0917
    part: Part,
    rule: Rule,
    stress: float,
    ids: tuple[int, ...],
    tj: float | None,
    t_ambient: float | None,
    sink: DiagnosticSink,
) -> DeratingResult:
    rating = part.ratings.get(rule.rating)
    if rating is None:
        sink.warning(
            "DERATING_NO_RATING",
            f"{part.refdes}: rule {rule.id} needs rating {rule.rating!r}; status UNKNOWN",
            part_id=part.id,
        )
        return DeratingResult(
            part_id=part.id or 0,
            param=rule.param,
            stress=stress,
            limit=None,
            rating=None,
            ratio=None,
            status=DeratingStatus.UNKNOWN,
            margin=None,
            rule_id=rule.id,
            stress_value_ids=ids,
        )
    rated = rating.value
    limit = rule.factor * rated + rule.offset
    if rule.curve is not None:
        limit = _curve_limit(part, rule, rated, tj if tj is not None else t_ambient, sink)
    ratio = stress / limit if limit else float("inf")
    margin = (limit - stress) / limit if limit else float("-inf")
    if stress <= limit:
        status = DeratingStatus.PASS
    elif stress <= rated:  # between the derated limit and the absolute rating
        status = DeratingStatus.WARN
    else:
        status = DeratingStatus.FAIL
    return DeratingResult(
        part_id=part.id or 0,
        param=rule.param,
        stress=stress,
        limit=limit,
        rating=rated,
        ratio=ratio,
        status=status,
        margin=margin,
        rule_id=rule.id,
        stress_value_ids=ids,
    )


def _curve_limit(
    part: Part, rule: Rule, rated: float, t_part: float | None, sink: DiagnosticSink
) -> float:
    assert rule.curve is not None
    knee = part.ratings.get(rule.curve[0])
    tmax = part.ratings.get(rule.curve[1])
    if t_part is None or knee is None or tmax is None or tmax.value <= knee.value:
        sink.info(
            "DERATING_CURVE_INCOMPLETE",
            f"{part.refdes}: temperature curve for {rule.id} needs {rule.curve[0]}, "
            f"{rule.curve[1]} "
            "and a part temperature; using the flat factor",
            part_id=part.id,
        )
        return rule.factor * rated
    scale = min(1.0, max(0.0, (tmax.value - t_part) / (tmax.value - knee.value)))
    return rated * scale * rule.factor


def _worst_stress_by_param(
    part_id: int, effective: Mapping[StressKey, StressValue]
) -> dict[str, StressValue]:
    worst: dict[str, StressValue] = {}
    for key, value in effective.items():
        if key.part_id != part_id:
            continue
        cur = worst.get(key.param)
        if cur is None or value.value > cur.value:
            worst[key.param] = value
    return worst


def _worst_tj(thermal: list[ThermalResult]) -> dict[int, float]:
    out: dict[int, float] = {}
    for t in thermal:
        out[t.part_id] = max(out.get(t.part_id, float("-inf")), t.tj)
    return out
