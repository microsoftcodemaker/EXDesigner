"""Flyback: CCM/DCM equations vs hand calculations (0.1 %), pattern on a synthetic Protel
netlist, template defaults/prompts and M2 binding (PRD 3.2, T27, OPC-05).

Case F1 by hand (CCM): Vin 48, Vout 12, Iout 2, fsw 100 kHz, Lp 200 uH, n 2, eta 0.9, Vf 0.5,
Vspike 10.  Pin = 24/0.9 = 26.6667 W; Vr = 2*12.5 = 25; D = 25/73 = 0.342466;
Iavg_pri = 26.6667/(48*0.342466) = 1.622222; DI = 48*0.342466/20 = 0.821918 -> valley > 0: CCM;
Ipk = 1.622222 + 0.410959 = 2.033181; Irms_pri = sqrt(0.342466*(2.631605 + 0.056296)) = 0.959434;
Isec_on = 2/0.657534 = 3.041667, DIs = 1.643836, Ipk_sec = 3.863584,
Irms_sec = sqrt(0.657534*(9.251736 + 0.225183)) = 2.496277; Vds = 48 + 25 + 10 = 83;
PIV = 12 + 48/2 = 36; Icin = sqrt(0.920514 - 0.308642) = 0.782222; Icout = 1.493787.
"""

from __future__ import annotations

import pytest

from dfr.core.contracts import (
    ConverterSpec,
    Part,
    PartClass,
    Rating,
    RatingProvenance,
    RatingSet,
    RoleMap,
    Severity,
)
from dfr.core.ports import FixedClock
from dfr.modules.m1_bom.netlist.service import import_netlist
from dfr.modules.m2_conditions.service import compute_template_stress
from dfr.topologies.flyback.equations import FlybackInputError, flyback_point
from dfr.topologies.flyback.pattern import FlybackPattern
from dfr.topologies.flyback.template import FlybackTemplate, load_defaults
from tests.conftest import protel_netlist

REL = 1e-3
CASES = [
    # (vin, vout, iout, fsw, lp, n, eta, vf, spike) -> mode, D, D2, Ipk, Irms_pri, Ipk_sec,
    #                                                 Irms_sec, Vds, PIV, Icin, Icout
    (
        (48, 12, 2, 1e5, 200e-6, 2, 0.9, 0.5, 10),
        (
            "ccm",
            0.342466,
            0.657534,
            2.033181,
            0.959434,
            3.863584,
            2.496277,
            83,
            36,
            0.782222,
            1.493787,
        ),
    ),
    (
        (24, 5, 1, 1e5, 20e-6, 3, 0.85, 0.4, 0),
        (
            "dcm",
            0.202113,
            0.299427,
            2.425356,
            0.629524,
            7.276069,
            2.298695,
            40.2,
            13,
            0.579851,
            2.069783,
        ),
    ),
    (
        (300, 12, 1, 6.5e4, 1.5e-3, 10, 0.85, 0.7, 40),
        (
            "dcm",
            0.174895,
            0.413138,
            0.538138,
            0.129934,
            5.381382,
            1.997012,
            467,
            42,
            0.121112,
            1.728599,
        ),
    ),
]


@pytest.mark.parametrize(("args", "expected"), CASES)
def test_flyback_hand_calcs(args, expected) -> None:
    vin, vout, iout, fsw, lp, n, eta, vf, spike = args
    p = flyback_point(
        vin=vin, vout=vout, iout=iout, fsw=fsw, lp=lp, n=n, eta=eta, vf=vf, v_spike=spike
    )
    assert p.mode == expected[0]
    got = (
        p.duty,
        p.duty_off,
        p.i_pri_peak,
        p.i_pri_rms,
        p.i_sec_peak,
        p.i_sec_rms,
        p.v_ds_max,
        p.v_diode_piv,
        p.i_cin_rms,
        p.i_cout_rms,
    )
    assert got == pytest.approx(expected[1:], rel=REL)


def test_dcm_peak_matches_ccm_at_boundary() -> None:
    """Continuity: at the CCM/DCM edge the two Ipk formulas agree (PRD boundary rule)."""
    # Vin 48, Vr 25, D 0.342466; boundary Lp = Vin^2 D^2 / (2 Pin fsw) for Pin 26.6667, 100 kHz
    lp_b = 48**2 * 0.342466**2 / (2 * 26.666667 * 1e5)
    ccm = flyback_point(vin=48, vout=12, iout=2, fsw=1e5, lp=lp_b * 1.001, n=2, eta=0.9, vf=0.5)
    dcm = flyback_point(vin=48, vout=12, iout=2, fsw=1e5, lp=lp_b * 0.999, n=2, eta=0.9, vf=0.5)
    assert (ccm.mode, dcm.mode) == ("ccm", "dcm")
    assert ccm.i_pri_peak == pytest.approx(dcm.i_pri_peak, rel=2e-3)
    assert abs(ccm.boundary_margin) < 0.01 and abs(dcm.boundary_margin) < 0.01


@pytest.mark.parametrize("kw", [{"n": 0}, {"eta": 1.2}, {"vin": 0}, {"lp": -1e-6}])
def test_flyback_rejects_invalid(kw) -> None:
    args = {"vin": 48, "vout": 12, "iout": 2, "fsw": 1e5, "lp": 2e-4, "n": 2, "eta": 0.9} | kw
    with pytest.raises(FlybackInputError):
        flyback_point(**args)


def _part(ref, cls, pid, value=None, **ratings) -> Part:
    return Part(
        id=pid,
        refdes=ref,
        part_class=cls,
        value_si=value,
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit="-", provenance=RatingProvenance.USER)
                for k, v in ratings.items()
            }
        ),
    )


# T1 pins 1-2 primary (VIN, DRAIN), 3-4 secondary (SEC, GND); Q1 drain DRAIN, source CS -> R1 -> GND
NETS = {
    "VIN": ["T1-1", "C1-1", "R3-1"],
    "DRAIN": ["T1-2", "Q1-3", "D2-1"],
    "CLAMP": ["D2-2", "R3-2", "C4-1"],
    "CS": ["Q1-2", "R1-1", "U1-3"],
    "GATE": ["Q1-1", "U1-1"],
    "SEC": ["T1-3", "D1-1"],
    "VOUT": ["D1-2", "C2-1", "C3-1"],
    "GND": ["T1-4", "C1-2", "C2-2", "C3-2", "R1-2", "U1-2", "C4-2"],
}
PARTS = [
    _part("T1", PartClass.TRANSFORMER, 1, turns_ratio=2.0, l_primary=200e-6),
    _part("Q1", PartClass.TRANSISTOR, 2, rds_on=0.1),
    _part("D1", PartClass.DIODE, 3, vf=0.5),
    _part("D2", PartClass.DIODE, 4),
    _part("C1", PartClass.CAPACITOR, 5, 47e-6),
    _part("C2", PartClass.CAPACITOR, 6, 100e-6),
    _part("C3", PartClass.CAPACITOR, 7, 100e-6),
    _part("C4", PartClass.CAPACITOR, 8, 1e-9),
    _part("R1", PartClass.RESISTOR, 9, 0.1),
    _part("R3", PartClass.RESISTOR, 10, 47e3),
    _part("U1", PartClass.IC, 11, eta=0.9),
]


def test_flyback_pattern() -> None:
    comps = {p.refdes: p.refdes for p in PARTS}
    out = import_netlist(protel_netlist(comps, NETS), "fly.net")
    assert not [d for d in out.diagnostics if d.severity is Severity.ERROR]
    m = FlybackPattern().match(out.graph, PARTS)[0]
    assert m.rails == {"vin": "VIN", "sw": "DRAIN", "vout": "VOUT", "gnd": "GND"}
    assert m.roles["primary_switch"] == ("Q1",) and m.roles["sense_resistor"] == ("R1",)
    assert m.roles["output_diode"] == ("D1",) and m.roles["clamp"] == ("D2",)
    assert m.roles["output_cap"] == ("C2", "C3") and m.roles["controller"] == ("U1",)
    assert not m.unmet


def test_flyback_through_m2(clock: FixedClock) -> None:
    roles = RoleMap(
        roles={
            "transformer": ("T1",),
            "primary_switch": ("Q1",),
            "output_diode": ("D1",),
            "output_cap": ("C2", "C3"),
            "input_cap": ("C1",),
            "controller": ("U1",),
        },
    )
    spec = ConverterSpec(vin_min=36, vin_max=48, vout=12, iout_max=2, fsw=1e5, t_ambient=25)
    out = compute_template_stress(FlybackTemplate(), spec, PARTS, roles, clock)
    assert out.params["n"] == 2 and out.params["lp"] == 200e-6 and out.params["eta"] == 0.9
    got = {(s.part_id, s.param, s.scenario): s for s in out.stress}
    assert got[(2, "i_rms", "vin_max")].value == pytest.approx(0.959434, rel=REL)  # case F1
    # no clamp rating -> Vspike = 0.30 * Vr = 7.5 V (data-file default, stated)
    assert got[(2, "v_peak", "vin_max")].value == pytest.approx(48 + 25 + 7.5, rel=REL)
    assert "assumed" in (got[(2, "v_peak", "vin_max")].note or "")
    assert got[(3, "v_peak", "vin_max")].value == pytest.approx(36, rel=REL)
    assert got[(2, "p_loss", "vin_max")].value == pytest.approx(0.959434**2 * 0.1, rel=REL)
    assert out.prompts == []


def test_flyback_prompts_for_transformer_data(clock: FixedClock) -> None:
    bare = [p.model_copy(update={"ratings": RatingSet()}) if p.refdes == "T1" else p for p in PARTS]
    roles = RoleMap(roles={"transformer": ("T1",), "primary_switch": ("Q1",)})
    spec = ConverterSpec(vin_min=36, vin_max=48, vout=12, iout_max=2, fsw=1e5, t_ambient=25)
    out = compute_template_stress(FlybackTemplate(), spec, bare, roles, clock)
    assert out.stress == []
    assert {p.param for p in out.prompts} == {"turns_ratio", "l_primary"}
    assert all(p.part_id == 1 for p in out.prompts)


def test_defaults_file_is_cited() -> None:
    d = load_defaults()
    assert "verify" in d["source"] and 0 < d["eta"] < 1 and d["sha256"]
