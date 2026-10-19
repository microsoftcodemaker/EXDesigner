from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dfr.core.contracts import (
    Part,
    PartClass,
    Rating,
    RatingProvenance,
    RatingSet,
    Source,
    Stat,
    StressValue,
    Tier,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.equations.thermal import ThermalPath, solve_tj
from dfr.modules.m6_thermal.module import solve_thermal

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def part(pid: int, refdes: str, cls: PartClass, **ratings: float) -> Part:
    return Part(
        id=pid,
        refdes=refdes,
        part_class=cls,
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit="", provenance=RatingProvenance.SEED)
                for k, v in ratings.items()
            }
        ),
    )


def sv(
    pid: int, param: str, value: float, scenario: str = "vin_max", sid: int | None = None
) -> StressValue:
    return StressValue(
        id=sid,
        part_id=pid,
        param=param,
        value=value,
        unit="W",
        stat=Stat.AVG,
        scenario=scenario,
        source=Source.EQUATION,
        tier=Tier.T1,
        tool="t",
        tool_version="1",
        timestamp=NOW,
    )


# ----------------------------------------------------------------------------- equations (THM-01/02)


def test_tj_board_level_hand_calc() -> None:
    # Tj = 40 + 1.2 W * 50 K/W = 100 C
    s = solve_tj(ta=40, path=ThermalPath(theta_ja=50), p_other=1.2)
    assert s.tj == pytest.approx(100.0) and s.converged and not s.runaway and s.tc is None


def test_tj_heatsink_chain_hand_calc() -> None:
    # Tc = 25 + 10*(0.5+2.0) = 50; Tj = 50 + 10*1.0 = 60
    s = solve_tj(ta=25, path=ThermalPath(theta_jc=1.0, theta_cs=0.5, theta_sa=2.0), p_other=10)
    assert s.tj == pytest.approx(60.0) and s.tc == pytest.approx(50.0)


def test_rds_on_iteration_converges_to_fixed_point() -> None:
    """Ta 40, theta 40 K/W, Irms 3 A, Rds25 20 mohm, alpha 0.005, P_other 0.3 W.
    Fixed point: Tj = 40 + 40*(0.3 + 9*0.02*(1+0.005*(Tj-25)))
               = 40 + 12 + 7.2*(1 + 0.005 Tj - 0.125) = 52 + 6.3 + 0.036 Tj
               -> Tj (1 - 0.036) = 58.3 -> Tj = 60.477 C"""
    s = solve_tj(
        ta=40, path=ThermalPath(theta_ja=40), p_other=0.3, i_rms=3, rds_on_25=0.020, alpha=0.005
    )
    assert s.tj == pytest.approx(60.477, abs=0.1)
    assert s.converged and not s.runaway and s.iterations <= 20
    assert s.p_total == pytest.approx(0.3 + 9 * 0.020 * (1 + 0.005 * (s.tj - 25)), rel=1e-3)


def test_runaway_detected_when_loop_gain_exceeds_one() -> None:
    # gain = I^2 Rds alpha theta = 100 * 0.1 * 0.005 * 30 = 1.5 > 1 -> no fixed point
    s = solve_tj(
        ta=40, path=ThermalPath(theta_ja=30), p_other=0, i_rms=10, rds_on_25=0.1, alpha=0.005
    )
    assert s.runaway and not s.converged


def test_tj_max_exceeded_flags_runaway_risk() -> None:
    s = solve_tj(
        ta=40, path=ThermalPath(theta_ja=60), p_other=2.0, i_rms=2, rds_on_25=0.05, tj_max=150
    )
    assert s.runaway and s.tj > 150


def test_incomplete_path_raises() -> None:
    with pytest.raises(ValueError, match="theta"):
        solve_tj(ta=25, path=ThermalPath(theta_jc=1.0), p_other=1.0)
    assert ThermalPath(theta_jc=1.0).total is None and ThermalPath(theta_ja=5).total == 5


# ----------------------------------------------------------------------------- module (THM-01..03)


def test_solve_thermal_per_part_and_scenario() -> None:
    q = part(1, "Q1", PartClass.TRANSISTOR, theta_ja=40, rds_on=0.020, tj_max=150)
    L = part(2, "L1", PartClass.INDUCTOR, theta_ja=25)
    r = part(3, "R1", PartClass.RESISTOR, theta_ja=99)  # skipped: uses derating curve
    effective = {
        v.key: v
        for v in (
            sv(1, "p_loss", 0.3 + 9 * 0.020, sid=1),
            sv(1, "i_rms", 3.0, sid=2),
            sv(1, "p_loss", 0.5, "vin_min", sid=3),
            sv(1, "i_rms", 2.0, "vin_min", sid=4),
            sv(2, "p_loss", 0.4, sid=5),
            sv(3, "p_loss", 0.05, sid=6),
        )
    }
    effective[sv(1, "i_rms", 3.0).key] = sv(1, "i_rms", 3.0, sid=2).model_copy(
        update={"unit": "A", "stat": Stat.RMS}
    )
    sink = DiagnosticSink("t")
    out = solve_thermal([q, L, r], effective, 40.0, sink=sink)
    by = {(t.part_id, t.scenario): t for t in out}
    assert set(by) == {(1, "vin_max"), (1, "vin_min"), (2, "vin_max")}
    assert by[(1, "vin_max")].tj == pytest.approx(60.477, abs=0.1)  # same fixed point as above
    assert by[(1, "vin_max")].stress_value_ids == (1, 2)
    assert by[(2, "vin_max")].tj == pytest.approx(40 + 0.4 * 25)
    assert not any(t.runaway_flag for t in out)
    assert not list(sink)


def test_missing_theta_is_diagnostic_not_guess() -> None:
    L = part(2, "L1", PartClass.INDUCTOR)
    sink = DiagnosticSink("t")
    out = solve_thermal([L], {sv(2, "p_loss", 0.4).key: sv(2, "p_loss", 0.4)}, 40.0, sink=sink)
    assert out == [] and [d.code for d in sink] == ["THERMAL_NO_THETA"]


def test_runaway_reported_as_error() -> None:
    q = part(1, "Q1", PartClass.TRANSISTOR, theta_ja=60, rds_on=0.05, tj_max=150)
    effective = {v.key: v for v in (sv(1, "p_loss", 2.0), sv(1, "i_rms", 2.0))}
    sink = DiagnosticSink("t")
    out = solve_thermal([q], effective, 40.0, sink=sink)
    assert out[0].runaway_flag and any(d.code == "THERMAL_RUNAWAY_RISK" for d in sink)
