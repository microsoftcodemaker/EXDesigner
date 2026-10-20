"""PoF Weibull roll-up (MTB-03/04): MTTF = eta*Gamma(1+1/beta), B10, series product, no MTBF."""

from __future__ import annotations

import pytest

from dfr.core.contracts import Confidence, LifetimeResult
from dfr.modules.m8_failure_rate.pof import eta_from_life, weibull_rollup
from dfr.modules.m8_failure_rate.tables import load_table


def lr(pid, mech, life, model="m") -> LifetimeResult:
    return LifetimeResult(
        part_id=pid,
        mechanism=mech,
        model_id=model,
        life_hours=life,
        confidence=Confidence.LOW,
        assumptions=("not available: x",) if life is None else (),
    )


@pytest.fixture(scope="module")
def pof():
    t = load_table("pof")
    assert t is not None and t.version == 1 and t.betas["electrolyte_dry_out"] == 3.0
    return t


def test_single_mechanism_closed_form(pof) -> None:
    # eta 1e5 h, beta 3: MTTF = 1e5 * Gamma(4/3) = 89297.95 h; B10 = 1e5 * (-ln 0.9)^(1/3) = 47230.87 h
    r = weibull_rollup([lr(1, "electrolyte_dry_out", 1e5), lr(2, "contact_wear", None)], pof)
    assert r.system_mttf_h == pytest.approx(89297.95, rel=1e-3)
    assert r.b10_h == pytest.approx(47230.87, rel=1e-3)
    assert r.system_mtbf_h is None and r.system_lambda_fit is None
    assert r.excluded_part_ids == [2] and r.excluded_reasons[2] == "not available: x"
    # average hazard over the 10 y target: R(87660) = 0.50987 -> 7684 FIT
    assert r.per_part[0].lambda_fit == pytest.approx(7684.3, rel=1e-3)
    assert r.per_part[0].factors["beta"] == 3.0 and r.reliability_curve is not None
    assert r.reliability_curve[-1][1] < 1e-6


def test_two_mechanisms_series(pof) -> None:
    # eta 1e5/beta 3 and eta 2e5/beta 2: MTTF (numerical) 81827.8 h, B10 40199.2 h (bisection)
    r = weibull_rollup([lr(1, "electrolyte_dry_out", 1e5), lr(2, "contact_wear", 2e5)], pof)
    assert r.system_mttf_h == pytest.approx(81827.8, rel=1e-3)
    assert r.b10_h == pytest.approx(40199.2, rel=1e-3)
    assert [p.part_id for p in r.per_part] == [1, 2]  # worst average hazard first


def test_unknown_mechanism_uses_default_beta_and_b10_reading(pof) -> None:
    assert pof.beta_for("mystery") == (2.0, f"default_beta ({pof.source})")
    assert eta_from_life(47230.87, 3.0, "b10") == pytest.approx(1e5, rel=1e-3)
    assert eta_from_life(1e5, 3.0, "eta") == 1e5


def test_nothing_to_roll_up(pof) -> None:
    r = weibull_rollup([lr(1, "wear_out", None)], pof)
    assert r.system_mttf_h is None and r.reliability_curve is None and r.excluded_part_ids == [1]
    assert "nothing to roll up" in r.assumptions[-1]
