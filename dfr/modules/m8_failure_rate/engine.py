"""Parts-stress constant-rate engine (PRD 3.8 MIL-HDBK-217F / SR-332 structure, MTB-01/02/04).

    product form : lp = lambda_b * prod(pi_i)
    ic_sum form  : lp = (C1 * piT + C2 * piE) * prod(other pi_i)
    piT          : exp[-(Ea/kB) * (1/(T + 273.15) - 1/(T_ref + 273.15))]   (Arrhenius)
    system       : lambda_sys = sum(lambda_i);  MTBF = 1e9 / lambda_sys [h]  (FIT = 1e-9 /h)

A part whose entry or any factor input is missing is excluded with a reason (never a guessed
rate); the result lists them (PRD 3.8 edge cases).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dfr.core.contracts import (
    FailureRateResult,
    Part,
    PartFailureRate,
    StressKey,
    StressValue,
    ThermalResult,
)
from dfr.modules.m8_failure_rate.tables import Entry, Factor, FailureRateTable

KELVIN = 273.15
FIT_PER_HOUR = 1e9


class FactorUnavailable(Exception):
    """A factor input the table needs is missing for this part."""


@dataclass(frozen=True)
class PartContext:
    part: Part
    stress: Sequence[StressValue]
    tj: float | None
    t_ambient: float
    environment: str
    quality: str


def arrhenius(t_c: float, ea_ev: float, kb: float, t_ref_c: float = 25.0) -> float:
    """piT = exp[-(Ea/kB)(1/T - 1/Tref)], temperatures in degC converted to kelvin."""
    return math.exp(-(ea_ev / kb) * (1.0 / (t_c + KELVIN) - 1.0 / (t_ref_c + KELVIN)))


def interpolate(curve: Sequence[tuple[float, float]], x: float, *, log: bool = False) -> float:
    """Piecewise-linear lookup clamped at the ends; ``log`` interpolates on log10(x)."""
    pts = sorted(curve)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    f = math.log10 if log else (lambda v: v)
    for (x0, y0), (x1, y1) in itertools.pairwise(pts):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (f(x) - f(x0)) / (f(x1) - f(x0))
    return pts[-1][1]  # pragma: no cover - unreachable with sorted points


def evaluate_factor(f: Factor, pc: PartContext, table: FailureRateTable) -> float:
    if f.kind == "constant":
        return float(f.value or 0.0)
    if f.kind == "lookup":
        return _lookup(f, pc)
    if f.kind == "arrhenius":
        if pc.tj is None and f.requires_tj:
            raise FactorUnavailable(f"{f.name}: no junction temperature (M6 result)")
        t = pc.tj if pc.tj is not None else pc.t_ambient
        return arrhenius(t, float(f.ea_ev or 0.0), table.kb_ev_per_k, f.t_ref_c)
    if f.kind in ("stress_ratio", "value_curve"):
        return _curve_factor(f, pc)
    raise FactorUnavailable(f"{f.name}: unknown factor kind {f.kind}")


def _curve_factor(f: Factor, pc: PartContext) -> float:
    """stress_ratio: curve(worst stress / rating); value_curve: curve(part value)."""
    x: float | None
    why: str
    if f.kind == "stress_ratio":
        rows = [s for s in pc.stress if s.param == f.param]
        rating = pc.part.ratings.get(f.rating or "")
        ok = bool(rows) and rating is not None and rating.value > 0
        x = max(s.value for s in rows) / rating.value if ok and rating is not None else None
        why = f"needs stress {f.param} and rating {f.rating}"
    else:
        x, why = pc.part.value_si, "part has no value"
    if x is None:
        if f.default is not None:
            return f.default
        raise FactorUnavailable(f"{f.name}: {why}")
    return interpolate(f.curve, x, log=f.log)


def _lookup(f: Factor, pc: PartContext) -> float:
    by = f.by or ""
    if by == "quality":
        key = pc.part.attributes.get("quality", pc.quality)
    elif by == "environment":
        key = pc.environment
    elif by.startswith("attribute:"):
        key = pc.part.attributes.get(by.split(":", 1)[1], "")
    else:
        raise FactorUnavailable(f"{f.name}: unknown lookup key {by}")
    if key in f.table:
        return f.table[key]
    if f.default is not None:
        return f.default
    raise FactorUnavailable(f"{f.name}: no table row for {by} = {key or '<unset>'}")


def part_rate_fit(entry: Entry, pc: PartContext, table: FailureRateTable) -> PartFailureRate:
    """lambda of one part in FIT with every factor it used (raises FactorUnavailable)."""
    factors = {f.name: evaluate_factor(f, pc, table) for f in entry.factors}
    if entry.form == "ic_sum":
        pi_t, pi_e = factors.get("piT", 1.0), factors.get("piE", 1.0)
        rest = math.prod(v for k, v in factors.items() if k not in ("piT", "piE"))
        lam = (entry.c1 * pi_t + entry.c2 * pi_e) * rest
    else:
        lam = entry.lambda_b * math.prod(factors.values())
    factors["t_c"] = pc.tj if pc.tj is not None else pc.t_ambient
    return PartFailureRate(
        part_id=pc.part.id or 0, lambda_fit=lam * table.fit_per_unit, factors=factors
    )


def parts_stress(  # noqa: PLR0917
    parts: Sequence[Part],
    effective: Mapping[StressKey, StressValue],
    table: FailureRateTable,
    thermal: Sequence[ThermalResult] | None = None,
    t_ambient: float = 25.0,
    environment: str | None = None,
    quality: str | None = None,
) -> FailureRateResult:
    """Series system over every non-DNP part with a table entry (MTB-01, MTB-04)."""
    env = environment or table.environment
    qual = quality or table.quality
    worst_tj: dict[int, float] = {}
    for t in thermal or []:
        worst_tj[t.part_id] = max(worst_tj.get(t.part_id, float("-inf")), t.tj)
    per_part: list[PartFailureRate] = []
    excluded: dict[int, str] = {}
    used_ta: list[str] = []
    for part in parts:
        if part.id is None or part.dnp:
            continue
        entry = table.entry_for(part.part_class.value, part.subtype)
        if entry is None:
            excluded[part.id] = f"no table entry for {part.part_class.value}/{part.subtype or '-'}"
            continue
        pc = PartContext(
            part,
            [v for k, v in effective.items() if k.part_id == part.id],
            worst_tj.get(part.id),
            t_ambient,
            env,
            qual,
        )
        try:
            per_part.append(part_rate_fit(entry, pc, table))
        except FactorUnavailable as exc:
            excluded[part.id] = str(exc)
            continue
        if pc.tj is None and any(f.kind == "arrhenius" for f in entry.factors):
            used_ta.append(part.refdes)
    lam_sys = sum(p.lambda_fit for p in per_part) if per_part else None
    assumptions = [
        f"{table.standard or table.id}: {table.source} (confidence {table.confidence.value})",
        f"environment {env or '<unset>'}, quality {qual or '<unset>'}; "
        f"rates in {table.rate_unit} converted to FIT",
        f"series system: lambda_sys = sum(lambda_i); {len(per_part)} part(s) counted, "
        f"{len(excluded)} excluded (no entry or missing input, never guessed)",
    ]
    if used_ta:
        assumptions.append(
            f"no Tj for {', '.join(used_ta)}: piT evaluated at Ta {t_ambient:g} degC (optimistic)"
        )
    if table.is_empty:
        assumptions.append("table has no class entries: import one (docs/failure_rate_tables.md)")
    return FailureRateResult(
        method=table.id,
        per_part=sorted(per_part, key=lambda p: -p.lambda_fit),
        system_lambda_fit=lam_sys,
        system_mtbf_h=(FIT_PER_HOUR / lam_sys) if lam_sys else None,
        reliability_curve=_exp_curve(lam_sys) if lam_sys else None,
        assumptions=assumptions,
        excluded_part_ids=sorted(excluded),
        table_id=table.id,
        confidence=table.confidence,
        excluded_reasons=excluded,
    )


def _exp_curve(lam_fit: float, points: int = 60) -> list[tuple[float, float]]:
    """R(t) = exp(-lambda t) out to 3 MTBF on a log grid (for the comparison chart)."""
    mtbf = FIT_PER_HOUR / lam_fit
    return [
        (t, math.exp(-t / mtbf))
        for t in (10 ** (math.log10(mtbf * 3) * i / (points - 1)) for i in range(points))
    ]
