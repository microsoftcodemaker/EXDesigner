"""Physics-of-failure Weibull roll-up over M7 lifetime results (PRD 3.8, MTB-03/04).

    R_i(t)   = exp[-(t / eta_i)^beta_i]        eta_i from the M7 life (life_is = eta | b10)
    eta(b10) = L / (-ln 0.9)^(1/beta)          when the life is read as a B10
    R_sys(t) = prod_i R_i(t)
    MTTF     = integral_0^inf R_sys(t) dt      (trapezoid on a log time grid)
    B10      = t at R_sys = 0.9                (log-linear interpolation on the grid)

No MTBF: a wear-out roll-up is not constant-rate. ``PartFailureRate.lambda_fit`` holds the
equivalent average hazard over the target life, -ln R_i(T) / T, clearly labelled in ``factors``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from dfr.core.contracts import FailureRateResult, LifetimeResult, PartFailureRate
from dfr.modules.m8_failure_rate.tables import FailureRateTable

FIT_PER_HOUR = 1e9
LN_0_9 = -math.log(0.9)


def eta_from_life(life_h: float, beta: float, life_is: str) -> float:
    if life_is == "b10":
        return float(life_h / LN_0_9 ** (1.0 / beta))
    return life_h


def weibull_r(t: np.ndarray, eta: float, beta: float) -> np.ndarray:
    return np.exp(-((t / eta) ** beta))


def weibull_rollup(
    lifetimes: Sequence[LifetimeResult],
    table: FailureRateTable,
    *,
    target_life_h: float = 87660.0,
) -> FailureRateResult:
    """System reliability curve, MTTF and B10 from every M7 result with a life (MTB-03)."""
    items: list[tuple[LifetimeResult, float, float, str]] = []
    excluded: dict[int, str] = {}
    for lr in lifetimes:
        if lr.life_hours is None or lr.life_hours <= 0:
            excluded.setdefault(
                lr.part_id, lr.assumptions[0] if lr.assumptions else "lifetime not available"
            )
            continue
        beta, src = table.beta_for(lr.mechanism)
        items.append((lr, eta_from_life(lr.life_hours, beta, table.life_is), beta, src))
    for lr, _eta, _b, _s in items:
        excluded.pop(lr.part_id, None)  # a part with one usable mechanism counts
    assumptions = [
        f"{table.source} (confidence {table.confidence.value}); M7 life read as "
        f"{'B10' if table.life_is == 'b10' else 'characteristic life eta (63.2 %)'}",
        "series system R_sys(t) = prod R_i(t); MTTF by trapezoid on a log grid; "
        "no MTBF for wear-out (MTB-04)",
        f"{len(items)} mechanism(s) over {len({lr.part_id for lr, *_ in items})} part(s); "
        f"{len(excluded)} part(s) without a life estimate excluded",
    ]
    if not items:
        return FailureRateResult(
            method=table.id,
            assumptions=[*assumptions, "no lifetime estimates: nothing to roll up"],
            excluded_part_ids=sorted(excluded),
            table_id=table.id,
            confidence=table.confidence,
            excluded_reasons=excluded,
        )
    t_max = max(eta for _lr, eta, _b, _s in items) * 10.0
    t = np.logspace(math.log10(table.grid_t_min_h), math.log10(t_max), table.grid_points)
    r_sys = np.ones_like(t)
    per_part: list[PartFailureRate] = []
    for lr, eta, beta, _src in items:
        r_sys *= weibull_r(t, eta, beta)
        r_target = float(math.exp(-((target_life_h / eta) ** beta)))
        lam_avg = -math.log(r_target) / target_life_h if r_target > 0 else float("inf")
        per_part.append(
            PartFailureRate(
                part_id=lr.part_id,
                lambda_fit=lam_avg * FIT_PER_HOUR,
                factors={
                    "eta_h": eta,
                    "beta": beta,
                    "r_target": r_target,
                    "target_life_h": target_life_h,
                },
            )
        )
    mttf = float(np.trapezoid(r_sys, t)) + float(t[0])  # R ~ 1 below the first grid point
    b10 = _time_at(t, r_sys, 0.9)
    step = max(1, len(t) // 200)
    curve = [(float(x), float(y)) for x, y in zip(t[::step], r_sys[::step], strict=False)]
    return FailureRateResult(
        method=table.id,
        per_part=sorted(per_part, key=lambda p: -p.lambda_fit),
        system_lambda_fit=None,
        system_mtbf_h=None,
        reliability_curve=curve,
        assumptions=assumptions,
        excluded_part_ids=sorted(excluded),
        system_mttf_h=mttf,
        b10_h=b10,
        table_id=table.id,
        confidence=table.confidence,
        excluded_reasons=excluded,
    )


def _time_at(t: np.ndarray, r: np.ndarray, level: float) -> float | None:
    """First grid time where R drops to ``level`` (log-linear interpolation)."""
    idx = int(np.argmax(r <= level))
    if r[idx] > level:
        return None
    if idx == 0:
        return float(t[0])
    t0, t1, r0, r1 = t[idx - 1], t[idx], r[idx - 1], r[idx]
    frac = (r0 - level) / (r0 - r1) if r0 != r1 else 0.0
    return float(10 ** (math.log10(t0) + frac * (math.log10(t1) - math.log10(t0))))
