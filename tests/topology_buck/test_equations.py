"""Hand-calculated cases (PRD 8.1: >= 3 per equation, 0.1 % tolerance) and property tests."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dfr.core.equations.losses import (
    mosfet_loss,
    p_conduction,
    p_diode,
    p_gate,
    p_inductor_copper,
    p_reverse_recovery,
    p_switching,
    rds_on_at,
)
from dfr.topologies.buck.equations import BuckInputError, buck_point

TOL = 1e-3  # 0.1 %


def test_design_a_prd_table() -> None:
    """PRD 8.2 Design A: Vin 24, Vout 5, Iout 3, fsw 500 kHz, L 4.7 uH, Cout 144 uF."""
    p = buck_point(vin=24, vout=5, iout=3, fsw=500e3, inductance=4.7e-6, cout=144e-6, dcr=0.020)
    assert p.duty == pytest.approx(0.2083, rel=TOL)
    assert p.ripple_pp == pytest.approx(1.684, rel=TOL)
    assert p.il_peak == pytest.approx(3.842, rel=TOL)
    assert p.il_rms == pytest.approx(3.039, rel=TOL)
    assert p.i_hs_rms == pytest.approx(1.387, rel=TOL)
    assert p.i_ls_rms == pytest.approx(2.704, rel=TOL)
    assert p.i_cin_rms == pytest.approx(1.218, rel=TOL)
    assert p.i_cout_rms == pytest.approx(0.486, rel=TOL)
    assert p.v_sw_max == 24
    assert p.ccm and not p.near_boundary
    # P_cu = IL_rms^2 * DCR = 3.039^2 * 0.020 = 0.1847 W
    assert p.p_inductor_cu == pytest.approx(0.1847, rel=TOL)
    # dVout = DIL/(8 fsw Cout) = 1.684/(8*500e3*144e-6) = 2.92 mV (ESR 0)
    assert p.v_out_ripple == pytest.approx(2.924e-3, rel=TOL)


def test_hand_case_12v_to_3v3() -> None:
    """Vin 12, Vout 3.3, Iout 2, fsw 1 MHz, L 2.2 uH.
    D = 0.275; DIL = 3.3*0.725/(2.2e-6*1e6) = 1.0875 A; IL_pk = 2.54375;
    IL_rms = sqrt(4 + 1.0875^2/12) = sqrt(4.09855) = 2.02449;
    HS = sqrt(0.275*4.09855) = 1.06163; LS = sqrt(0.725*4.09855) = 1.72373;
    Cin = 2*sqrt(0.275*0.725) = 0.89303; Cout = 1.0875/(2*sqrt3) = 0.31393."""
    p = buck_point(vin=12, vout=3.3, iout=2, fsw=1e6, inductance=2.2e-6)
    assert p.duty == pytest.approx(0.275, rel=TOL)
    assert p.ripple_pp == pytest.approx(1.0875, rel=TOL)
    assert p.il_peak == pytest.approx(2.54375, rel=TOL)
    assert p.il_rms == pytest.approx(2.02449, rel=TOL)
    assert p.i_hs_rms == pytest.approx(1.06163, rel=TOL)
    assert p.i_ls_rms == pytest.approx(1.72373, rel=TOL)
    assert p.i_cin_rms == pytest.approx(0.89303, rel=TOL)
    assert p.i_cout_rms == pytest.approx(0.31393, rel=TOL)
    assert p.i_ls_avg == pytest.approx(1.45, rel=TOL)


def test_hand_case_asynchronous_diode() -> None:
    """Vin 36, Vout 12, Iout 1, fsw 300 kHz, L 33 uH, Vd 0.5.
    D = 12.5/36.5 = 0.342466; DIL = 12*(1-0.342466)/(33e-6*300e3) = 0.797011 A."""
    p = buck_point(vin=36, vout=12, iout=1, fsw=300e3, inductance=33e-6, diode_drop=0.5)
    assert p.duty == pytest.approx(0.342466, rel=TOL)
    assert p.ripple_pp == pytest.approx(0.797011, rel=TOL)
    assert p.ccm and not p.near_boundary  # edge margin = (1-0.3985)/1 = 0.60


def test_dcm_and_boundary_flags() -> None:
    # Design A at Iout = 0.8 A: DIL/2 = 0.842 > 0.8 -> DCM
    p = buck_point(vin=24, vout=5, iout=0.8, fsw=500e3, inductance=4.7e-6)
    assert not p.ccm and p.near_boundary and p.il_valley < 0
    # Iout = 1.0 A: margin = (1 - 0.842)/1 = 0.158 -> within 20 % band (F5)
    p = buck_point(vin=24, vout=5, iout=1.0, fsw=500e3, inductance=4.7e-6)
    assert p.ccm and p.near_boundary
    # Iout = 3 A: margin 0.72 -> clear
    assert not buck_point(vin=24, vout=5, iout=3, fsw=500e3, inductance=4.7e-6).near_boundary


@pytest.mark.parametrize(
    "kw",
    [
        {"vin": 5, "vout": 5},  # D = 1
        {"vin": 3, "vout": 5},  # D > 1
        {"vin": 24, "vout": 5, "fsw": 0},
        {"vin": 24, "vout": 5, "inductance": -1e-6},
        {"vin": 24, "vout": 5, "iout": 0},
        {"vin": float("nan"), "vout": 5},
    ],
)
def test_invalid_inputs_rejected(kw: dict[str, float]) -> None:
    base = {"vin": 24.0, "vout": 5.0, "iout": 3.0, "fsw": 500e3, "inductance": 4.7e-6}
    base.update(kw)
    with pytest.raises(BuckInputError):
        buck_point(**base)


@settings(max_examples=200, deadline=None)
@given(
    vin=st.floats(6, 60),
    ratio=st.floats(0.05, 0.95),
    iout=st.floats(0.1, 20),
    fsw=st.floats(50e3, 2e6),
    L=st.floats(1e-6, 100e-6),
)
def test_properties(vin: float, ratio: float, iout: float, fsw: float, L: float) -> None:
    p = buck_point(vin=vin, vout=vin * ratio, iout=iout, fsw=fsw, inductance=L)
    assert 0 < p.duty < 1
    assert p.il_rms >= iout  # ripple only adds RMS
    assert p.il_peak > iout > p.il_valley
    assert p.i_hs_rms**2 + p.i_ls_rms**2 == pytest.approx(p.il_rms**2, rel=1e-9)
    assert p.i_cin_rms <= iout / 2 + 1e-12  # sqrt(D(1-D)) <= 0.5
    # Irms increases monotonically with Iout
    more = buck_point(vin=vin, vout=vin * ratio, iout=iout * 1.1, fsw=fsw, inductance=L)
    assert more.il_rms > p.il_rms and more.i_hs_rms > p.i_hs_rms


# ----------------------------------------------------------------------------- losses (T14)


def test_rds_on_temperature_and_conduction() -> None:
    # 10 mohm at 25 C, alpha 0.005: at 125 C -> 10m * 1.5 = 15 mohm
    assert rds_on_at(0.010, 125, 0.005) == pytest.approx(0.015, rel=TOL)
    assert rds_on_at(0.010, 25) == 0.010
    # P_cond = 2.704^2 * 15m = 0.10967 W
    assert p_conduction(2.704, 0.015) == pytest.approx(0.10967, rel=TOL)


def test_switching_gate_rr_diode_copper() -> None:
    # P_sw = 0.5*24*3*(10n+15n)*500k = 0.45 W
    assert p_switching(24, 3, 10e-9, 15e-9, 500e3) == pytest.approx(0.45, rel=TOL)
    # P_gate = 20nC * 10V * 500k = 0.1 W
    assert p_gate(20e-9, 10, 500e3) == pytest.approx(0.1, rel=TOL)
    # P_rr = 50nC * 24V * 500k = 0.6 W
    assert p_reverse_recovery(50e-9, 24, 500e3) == pytest.approx(0.6, rel=TOL)
    # Diode: Vf 0.45 * Iavg 2.375 + Rd 0.02 * Irms 2.704^2 = 1.06875 + 0.14623 = 1.21498
    assert p_diode(0.45, 2.375, 2.704, rd=0.02) == pytest.approx(1.21498, rel=TOL)
    assert p_inductor_copper(3.039, 0.020) == pytest.approx(0.1847, rel=TOL)


def test_mosfet_loss_reports_missing_data_instead_of_guessing() -> None:
    loss = mosfet_loss(i_rms=1.387, rds_on_25=0.010, tj_c=85, vds=24, i_switch=3, fsw=500e3)
    assert loss.p_cond == pytest.approx(1.387**2 * 0.010 * 1.3, rel=TOL)
    assert loss.p_sw is None and loss.p_gate is None and loss.p_coss is None
    assert set(loss.missing) == {"t_rise/t_fall", "coss_eq/eoss", "qg/vgs"}
    assert loss.total == pytest.approx(loss.p_cond)

    full = mosfet_loss(
        i_rms=1.387,
        rds_on_25=0.010,
        tj_c=25,
        vds=24,
        i_switch=3,
        fsw=500e3,
        t_rise=10e-9,
        t_fall=15e-9,
        qg=20e-9,
        vgs=10,
        eoss=2e-6,
        qrr=50e-9,
    )
    assert full.missing == ()
    expected = 1.387**2 * 0.010 + 0.45 + 0.1 + 2e-6 * 500e3 + 0.6
    assert full.total == pytest.approx(expected, rel=TOL)
    assert math.isclose(full.p_coss or 0, 1.0, rel_tol=TOL)
