from __future__ import annotations

import pytest

from dfr.core.contracts import Severity, Stat
from dfr.topologies.buck.template import BuckTemplate

DESIGN_A = {
    "vin_min": 24.0,
    "vin_max": 24.0,
    "vout": 5.0,
    "iout_max": 3.0,
    "fsw": 500e3,
    "t_ambient": 40.0,
    "L": 4.7e-6,
    "cout": 144e-6,
    "esr_eq": 0.0,
    "dcr": 0.020,
}


def _get(out, role: str, param: str, scenario: str = "vin_max"):
    return next(s for s in out.stress[role] if s.param == param and s.scenario == scenario)


def test_discrete_synchronous_design_a() -> None:
    t = BuckTemplate(integrated=False)
    assert t.validity_checks(DESIGN_A) == []
    out = t.compute_full(DESIGN_A)
    assert out.needs == []
    assert set(out.stress) == {
        "inductor",
        "output_cap",
        "input_cap",
        "high_side_switch",
        "low_side_switch",
    }
    assert _get(out, "high_side_switch", "i_rms").value == pytest.approx(1.387, rel=1e-3)
    assert _get(out, "low_side_switch", "i_rms").value == pytest.approx(2.704, rel=1e-3)
    assert _get(out, "high_side_switch", "v_peak").value == 24
    assert _get(out, "inductor", "i_peak").value == pytest.approx(3.842, rel=1e-3)
    assert _get(out, "inductor", "p_loss").value == pytest.approx(0.1847, rel=1e-3)
    assert _get(out, "output_cap", "i_rms").value == pytest.approx(0.486, rel=1e-3)
    assert _get(out, "input_cap", "i_rms").value == pytest.approx(1.218, rel=1e-3)
    assert _get(out, "output_cap", "v_ripple_pp").value == pytest.approx(2.924e-3, rel=1e-3)
    # both scenarios present and identical here (vin_min == vin_max)
    assert _get(out, "inductor", "i_rms", "vin_min").value == _get(out, "inductor", "i_rms").value
    assert all(s.stat is Stat.RMS for s in out.stress["high_side_switch"] if s.param == "i_rms")
    # compute() returns the same thing (interface)
    assert t.compute(DESIGN_A) == out.stress


def test_discrete_asynchronous_emits_diode_rows() -> None:
    params = {**DESIGN_A, "synchronous": 0.0, "vd": 0.5, "rds_hs": 0.010}
    out = BuckTemplate(integrated=False).compute_full(params)
    assert "low_side_switch" not in out.stress and "catch_diode" in out.stress
    assert _get(out, "catch_diode", "i_avg").value == pytest.approx(3 * (1 - 5.5 / 24.5), rel=1e-3)
    assert _get(out, "high_side_switch", "p_loss").value == pytest.approx(
        _get(out, "high_side_switch", "i_rms").value ** 2 * 0.010, rel=1e-9
    )
    missing_vd = BuckTemplate(integrated=False).compute_full({**DESIGN_A, "synchronous": 0.0})
    assert "vd" in missing_vd.needs


def test_integrated_ic_rows_and_loss_options() -> None:
    t = BuckTemplate(integrated=True)
    base = {
        **DESIGN_A,
        "vin_min": 8.0,
        "vin_max": 36.0,
        "vout": 3.3,
        "iout_max": 3.25,
        "fsw": 400e3,
        "L": 10e-6,
        "cout": 44e-6,
        "dcr": 0.08635,
    }
    # no Rds, no eta -> prompt, never a guessed loss
    out = t.compute_full(base)
    assert "p_ic" in out.needs
    assert any(d.code == "TEMPLATE_NEEDS_IC_LOSS" for d in out.diagnostics)
    assert not any(s.param == "p_loss" for s in out.stress["ic"])
    assert {s.param for s in out.stress["ic"]} == {
        "i_rms_hs",
        "i_rms_ls",
        "i_peak",
        "v_peak",
        "i_out",
    }
    assert _get(out, "ic", "v_peak").value == 36 and _get(out, "ic", "v_peak", "vin_min").value == 8
    assert _get(out, "ic", "i_out").value == 3.25

    # option 1: internal Rds_on (+ P_sw)
    o1 = t.compute_full({**base, "rds_hs": 0.05, "rds_ls": 0.03})
    assert "p_sw" in o1.needs and "p_ic" not in o1.needs
    p = _get(o1, "ic", "p_loss")
    assert p.value == pytest.approx(
        _get(o1, "ic", "i_rms_hs").value ** 2 * 0.05 + _get(o1, "ic", "i_rms_ls").value ** 2 * 0.03,
        rel=1e-9,
    )
    o1b = t.compute_full({**base, "rds_hs": 0.05, "rds_ls": 0.03, "p_sw": 0.2})
    assert _get(o1b, "ic", "p_loss").value == pytest.approx(p.value + 0.2) and o1b.needs == []

    # option 2: efficiency -> P_ic = Pout*(1/eta - 1) - P_cu
    o2 = t.compute_full({**base, "eta": 0.9})
    pout = 3.3 * 3.25
    il_rms = _get(o2, "inductor", "i_rms").value
    assert _get(o2, "ic", "p_loss").value == pytest.approx(
        pout * (1 / 0.9 - 1) - il_rms**2 * 0.08635, rel=1e-6
    )


def test_dcm_and_boundary_diagnostics_per_scenario() -> None:
    out = BuckTemplate(integrated=True).compute_full({**DESIGN_A, "iout_max": 0.8})
    codes = [d.code for d in out.diagnostics]
    assert codes.count("TEMPLATE_DCM") == 2  # both scenarios


def test_validity_checks() -> None:
    t = BuckTemplate(integrated=True)
    missing = t.validity_checks({"vin_min": 1.0})
    assert missing[0].code == "TEMPLATE_MISSING_INPUT" and missing[0].severity is Severity.ERROR
    bad = t.validity_checks({**DESIGN_A, "vin_min": 4.0})  # D > 1 at vin_min
    assert any(d.code == "TEMPLATE_INVALID_INPUT" and "vin_min" in d.message for d in bad)
    assert t.compute_full({**DESIGN_A, "vin_min": 4.0}).stress == {}
    no_cout = t.validity_checks({**DESIGN_A, "cout": 0.0})
    assert any(d.code == "TEMPLATE_NO_COUT" for d in no_cout)
    assert t.id == "buck_integrated" and t.pattern_id == "buck_integrated"
    assert BuckTemplate(integrated=False).id == "buck"
