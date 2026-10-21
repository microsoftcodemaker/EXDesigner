"""Boost / inverting buck-boost equations vs hand calculations (PRD 3.2), 0.1 % tolerance.

Case B1 by hand: Vin 5, Vout 12, Iout 1, fsw 500 kHz, L 10 uH, ideal rectifier.
  D = 1 - 5/12 = 0.583333;  IL_avg = 1/0.416667 = 2.4 A;  DIL = 5*0.583333/(10u*500k) = 0.583333
  IL_pk = 2.4 + 0.291667 = 2.691667;  IL_rms = sqrt(5.76 + 0.340278/12) = 2.405900
  Irms_Q = sqrt(0.583333*5.788356) = 1.837537;  Irms_D = sqrt(0.416667*5.788356) = 1.553002
  Icout = sqrt(1.553002^2 - 1) = 1.188198;  Icin = 0.583333/(2*sqrt 3) = 0.168394
Case BB1 by hand: Vin 12, |Vout| 12, Iout 1, fsw 500 kHz, L 22 uH: D = 0.5, IL_avg = 2,
  DIL = 12*0.5/11 = 0.545455, Irms_Q = Irms_D = sqrt(0.5*(4 + 0.024793)) = 1.418590,
  Icin = sqrt(2.012397 - 1) = 1.006179 = Icout, Vds_max = 24 V.
"""

from __future__ import annotations

import pytest

from dfr.topologies.boost.equations import BoostInputError, boost_point, buck_boost_point

REL = 1e-3

BOOST_CASES = [
    # (vin, vout, iout, fsw, L, vf) -> D, IL_avg, DIL, IL_pk, IL_rms, Irms_Q, Irms_D, Icout, Icin
    (
        (5, 12, 1, 5e5, 10e-6, 0.0),
        (0.583333, 2.4, 0.583333, 2.691667, 2.405900, 1.837537, 1.553002, 1.188198, 0.168394),
    ),
    (
        (3.3, 5, 2, 1e6, 2.2e-6, 0.4),
        (0.388889, 3.272727, 0.583333, 3.564394, 3.277057, 2.043604, 2.561793, 1.600870, 0.168394),
    ),
    (
        (9, 24, 0.5, 3e5, 47e-6, 0.5),
        (0.632653, 1.361111, 0.403821, 1.563022, 1.366094, 1.086584, 0.827978, 0.659960, 0.116573),
    ),
]
BB_CASES = [
    (
        (12, 12, 1, 5e5, 22e-6, 0.0),
        (0.5, 2.0, 0.545455, 2.272727, 2.006189, 1.418590, 1.418590, 1.006179, 1.006179),
    ),
    (
        (5, -15, 0.2, 4e5, 33e-6, 0.3),
        (0.753695, 0.812, 0.285490, 0.954745, 0.816172, 0.708564, 0.405059, 0.352240, 0.357098),
    ),
    (
        (24, 5, 1.5, 2e5, 47e-6, 0.0),
        (0.172414, 1.8125, 0.440205, 2.032603, 1.816949, 0.754447, 1.652911, 0.694344, 0.686683),
    ),
]


def _values(p):
    return (
        p.duty,
        p.il_avg,
        p.ripple_pp,
        p.il_peak,
        p.il_rms,
        p.i_sw_rms,
        p.i_d_rms,
        p.i_cout_rms,
        p.i_cin_rms,
    )


@pytest.mark.parametrize(("args", "expected"), BOOST_CASES)
def test_boost_hand_calcs(args, expected) -> None:
    vin, vout, iout, fsw, L, vf = args
    p = boost_point(vin=vin, vout=vout, iout=iout, fsw=fsw, inductance=L, vf=vf)
    assert _values(p) == pytest.approx(expected, rel=REL)
    assert p.v_sw_max == pytest.approx(vout + vf) and p.v_d_max == pytest.approx(vout)
    assert p.i_d_avg == iout and p.ccm


@pytest.mark.parametrize(("args", "expected"), BB_CASES)
def test_buck_boost_hand_calcs(args, expected) -> None:
    vin, vout, iout, fsw, L, vf = args
    p = buck_boost_point(vin=vin, vout=vout, iout=iout, fsw=fsw, inductance=L, vf=vf)
    assert _values(p) == pytest.approx(expected, rel=REL)
    assert p.v_d_max == pytest.approx(vin + abs(vout))
    assert p.v_sw_max == pytest.approx(vin + abs(vout) + vf)


def test_boost_ripple_and_copper_loss() -> None:
    # B1 with Cout 22 uF, ESR 10 mohm, DCR 50 mohm:
    # dV = 1*0.583333/(500k*22u) + 0.01*2.691667 = 0.053030 + 0.026917 = 0.079947 V
    # P_cu = 5.788356 * 0.05 = 0.289418 W
    p = boost_point(
        vin=5, vout=12, iout=1, fsw=5e5, inductance=10e-6, cout=22e-6, esr=0.01, dcr=0.05
    )
    assert p.v_out_ripple == pytest.approx(0.079947, rel=REL)
    assert p.p_inductor_cu == pytest.approx(0.289418, rel=REL)


def test_dcm_and_boundary_flags() -> None:
    # Iout 0.1 A at B1: IL_avg 0.24 < DIL/2 0.291667 -> DCM
    assert not boost_point(vin=5, vout=12, iout=0.1, fsw=5e5, inductance=10e-6).ccm
    # Iout 0.15: margin (0.36 - 0.291667)/0.36 = 0.19 -> near the edge
    p = boost_point(vin=5, vout=12, iout=0.15, fsw=5e5, inductance=10e-6)
    assert p.ccm and p.near_boundary


@pytest.mark.parametrize(
    "kw",
    [
        {"vin": 12, "vout": 5},  # boost cannot step down
        {"vin": -1, "vout": 12},
        {"vin": 5, "vout": 12, "vf": -0.1},
    ],
)
def test_boost_rejects_invalid(kw) -> None:
    with pytest.raises(BoostInputError):
        boost_point(iout=1, fsw=5e5, inductance=10e-6, **kw)
