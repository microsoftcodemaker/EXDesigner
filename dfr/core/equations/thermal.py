"""Steady-state junction temperature with Rds_on(Tj) self-heating (PRD 3.6, THM-01, THM-02).

    Tj = Ta + P * theta_JA                                  (board level)
    Tj = Tc + P * theta_JC;  Tc = Ta + P * (theta_CS + theta_SA)   (heatsink)
    P(Tj) = P_other + I_rms^2 * Rds_on_25 * (1 + alpha (Tj - 25))

Fixed-point iteration, tolerance 0.1 degC, max 20 iterations. If Tj exceeds Tj_max or
grows without converging, ``runaway`` is set and iteration stops (thermal_runaway_risk).
"""

from __future__ import annotations

from dataclasses import dataclass

from dfr.core.equations.losses import RDS_ON_ALPHA_DEFAULT, rds_on_at

TOLERANCE_C = 0.1
MAX_ITER = 20


@dataclass(frozen=True)
class ThermalPath:
    """Either theta_ja, or theta_jc with theta_cs + theta_sa (heatsink)."""

    theta_ja: float | None = None
    theta_jc: float | None = None
    theta_cs: float = 0.0
    theta_sa: float | None = None

    @property
    def total(self) -> float | None:
        if self.theta_ja is not None:
            return self.theta_ja
        if self.theta_jc is not None and self.theta_sa is not None:
            return self.theta_jc + self.theta_cs + self.theta_sa
        return None

    def case_temperature(self, ta: float, p: float) -> float | None:
        if self.theta_jc is not None and self.theta_sa is not None:
            return ta + p * (self.theta_cs + self.theta_sa)
        return None


@dataclass(frozen=True)
class ThermalSolution:
    tj: float
    tc: float | None
    p_total: float
    iterations: int
    converged: bool
    runaway: bool


def solve_tj(
    *,
    ta: float,
    path: ThermalPath,
    p_other: float,
    i_rms: float = 0.0,
    rds_on_25: float | None = None,
    alpha: float = RDS_ON_ALPHA_DEFAULT,
    tj_max: float | None = None,
) -> ThermalSolution:
    theta = path.total
    if theta is None:
        msg = "thermal path incomplete: need theta_ja, or theta_jc + theta_sa"
        raise ValueError(msg)
    if rds_on_25 is None or i_rms <= 0:
        p = p_other
        tj = ta + p * theta
        return ThermalSolution(
            tj, path.case_temperature(ta, p), p, 1, True, bool(tj_max is not None and tj > tj_max)
        )

    tj = ta
    p = p_other
    for n in range(1, MAX_ITER + 1):
        p = p_other + i_rms**2 * rds_on_at(rds_on_25, tj, alpha)
        tj_new = ta + p * theta
        if tj_max is not None and tj_new > tj_max:
            return ThermalSolution(tj_new, path.case_temperature(ta, p), p, n, False, True)
        if abs(tj_new - tj) <= TOLERANCE_C:
            return ThermalSolution(tj_new, path.case_temperature(ta, p), p, n, True, False)
        tj = tj_new
    # Loop gain i^2 * Rds25 * alpha * theta >= 1 means no finite fixed point: runaway.
    gain = i_rms**2 * rds_on_25 * alpha * theta
    return ThermalSolution(
        tj, path.case_temperature(ta, p), p, MAX_ITER, False, gain >= 1.0 or tj > 1e4
    )
