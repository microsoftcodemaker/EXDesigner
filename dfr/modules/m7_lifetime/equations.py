"""Wear-out equations (PRD section 3.7). Pure functions, SI/hours; every constant is passed in
so the data file, not the code, decides the numbers.

Aluminium electrolytic / polymer (manufacturer temperature rule, PRD 3.7 "Aluminum electrolytic"):
    dT_core = dT0 * (I_rms / I_rated)^2
    T_core  = Ta + dT_core
    L       = L0 * 2^((T0 - T_core) / degrees_per_doubling)       then min(L, L_cap)
MLCC (Prokopowicz-Vaskas, PRD 3.7 "MLCC"):
    L2 = L1 * (V1 / V2)^n * exp[(Ea / kB) * (1/T2 - 1/T1)]        T in kelvin
Thermal cycling (Coffin-Manson + Miner, PRD 3.7 "MOSFET/diode thermal cycling"):
    Nf_i = A * dTj_i^(-n);  D_per_year = sum_i n_i / Nf_i;  life_hours = hours_per_year / D
Connector (PRD 3.7 "Solder-joint and connector fatigue"):
    life_years = rated_mating_cycles / mating_cycles_per_year
"""

from __future__ import annotations

import math
from collections.abc import Iterable

HOURS_PER_YEAR = 8766.0
KELVIN = 273.15


def core_temperature(t_ambient: float, dt0_core: float, i_rms: float, i_rated: float) -> float:
    """Ta + dT0 * (Irms / Irated)^2; a zero ripple rating cannot be scaled (ValueError)."""
    if i_rated <= 0:
        msg = "i_rated must be positive"
        raise ValueError(msg)
    return t_ambient + dt0_core * (i_rms / i_rated) ** 2


def temperature_rule_life_hours(
    l0_hours: float, t0_rated: float, t_core: float, degrees_per_doubling: float
) -> float:
    """L0 * 2^((T0 - Tcore)/k). Extrapolates above T0 (caller flags it)."""
    if l0_hours <= 0 or degrees_per_doubling <= 0:
        msg = "l0_hours and degrees_per_doubling must be positive"
        raise ValueError(msg)
    return float(l0_hours * 2.0 ** ((t0_rated - t_core) / degrees_per_doubling))


def prokopowicz_vaskas_life_hours(  # noqa: PLR0917
    l1_hours: float,
    v1: float,
    t1_c: float,
    v2: float,
    t2_c: float,
    n: float,
    ea_ev: float,
    kb_ev_per_k: float,
) -> float:
    """Life at (V2, T2) from a qualification point (L1, V1, T1)."""
    if min(l1_hours, v1, v2) <= 0 or t1_c <= -KELVIN or t2_c <= -KELVIN:
        msg = "life, voltages must be positive and temperatures above absolute zero"
        raise ValueError(msg)
    t1, t2 = t1_c + KELVIN, t2_c + KELVIN
    return float(
        l1_hours * (v1 / v2) ** n * math.exp((ea_ev / kb_ev_per_k) * (1.0 / t2 - 1.0 / t1))
    )


def coffin_manson_cycles(a: float, n: float, delta_tj: float) -> float:
    """Nf = A * dTj^(-n)."""
    if a <= 0 or delta_tj <= 0:
        msg = "A and delta_tj must be positive"
        raise ValueError(msg)
    return float(a * delta_tj ** (-n))


def miner_life_hours(
    bins: Iterable[tuple[float, float]],
    a: float,
    n: float,
    *,
    hours_per_year: float = HOURS_PER_YEAR,
    min_delta_tj: float = 0.0,
) -> float | None:
    """Miner's rule over (dTj, cycles_per_year) bins; None when no bin counts (no damage)."""
    damage = 0.0
    for delta_tj, cycles in bins:
        if cycles <= 0 or delta_tj < min_delta_tj or delta_tj <= 0:
            continue
        damage += cycles / coffin_manson_cycles(a, n, delta_tj)
    return hours_per_year / damage if damage > 0 else None


def connector_life_hours(
    rated_mating_cycles: float,
    mating_cycles_per_year: float,
    *,
    hours_per_year: float = HOURS_PER_YEAR,
) -> float | None:
    """rated / per-year, in hours; None when the part is never mated (no wear-out)."""
    if rated_mating_cycles <= 0:
        msg = "rated_mating_cycles must be positive"
        raise ValueError(msg)
    if mating_cycles_per_year <= 0:
        return None
    return rated_mating_cycles / mating_cycles_per_year * hours_per_year
