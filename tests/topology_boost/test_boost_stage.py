"""Boost / buck-boost pattern on synthetic Protel netlists, template output and M2 binding."""

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
from dfr.core.registry import discover
from dfr.modules.m1_bom.netlist.service import import_netlist
from dfr.modules.m2_conditions.service import compute_template_stress
from dfr.topologies.boost.pattern import BOOST, BUCK_BOOST, BoostFamilyPattern
from dfr.topologies.boost.template import BoostFamilyTemplate
from tests.conftest import protel_netlist


def _part(ref: str, cls: PartClass, pid: int, value: float | None = None, **ratings: float) -> Part:
    unit = {PartClass.INDUCTOR: "H", PartClass.CAPACITOR: "F", PartClass.RESISTOR: "ohm"}
    return Part(
        id=pid,
        refdes=ref,
        part_class=cls,
        value_si=value,
        value_unit=unit.get(cls),
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit="-", provenance=RatingProvenance.USER)
                for k, v in ratings.items()
            }
        ),
    )


# Async boost: VIN -L1- SW; Q1 (D=SW, S=GND, G=GATE from U1); D1 SW->VOUT; C1 VIN, C2/C3 VOUT
BOOST_NETS = {
    "VIN": ["L1-1", "C1-1", "U1-1"],
    "SW": ["L1-2", "Q1-3", "D1-1"],
    "GATE": ["Q1-1", "U1-2"],
    "VOUT": ["D1-2", "C2-1", "C3-1", "R1-1"],
    "FB": ["R1-2", "R2-1", "U1-3"],
    "GND": ["Q1-2", "C1-2", "C2-2", "C3-2", "R2-2", "U1-4"],
}
BOOST_PARTS = [
    _part("L1", PartClass.INDUCTOR, 1, 10e-6, dcr=0.05),
    _part("Q1", PartClass.TRANSISTOR, 2),
    _part("D1", PartClass.DIODE, 3, vf=0.4),
    _part("C1", PartClass.CAPACITOR, 4, 10e-6),
    _part("C2", PartClass.CAPACITOR, 5, 22e-6),
    _part("C3", PartClass.CAPACITOR, 6, 22e-6),
    _part("U1", PartClass.IC, 7),
    _part("R1", PartClass.RESISTOR, 8, 100e3),
    _part("R2", PartClass.RESISTOR, 9, 10e3),
]
# Inverting buck-boost: Q1 VIN->SW, L1 SW->GND, D1 anode VNEG cathode SW, C2 VNEG-GND
BB_NETS = {
    "VIN": ["Q1-3", "C1-1"],
    "SW": ["Q1-2", "L1-1", "D1-2"],
    "GATE": ["Q1-1", "U1-1"],
    "VNEG": ["D1-1", "C2-1"],
    "GND": ["L1-2", "C1-2", "C2-2", "U1-2"],
}
BB_PARTS = [
    _part("L1", PartClass.INDUCTOR, 1, 22e-6),
    _part("Q1", PartClass.TRANSISTOR, 2),
    _part("D1", PartClass.DIODE, 3),
    _part("C1", PartClass.CAPACITOR, 4, 10e-6),
    _part("C2", PartClass.CAPACITOR, 5, 47e-6),
    _part("U1", PartClass.IC, 7),
]


def _graph(nets, parts):
    comps = {p.refdes: p.refdes for p in parts}
    out = import_netlist(protel_netlist(comps, nets), "synthetic.net")
    assert not [d for d in out.diagnostics if d.severity is Severity.ERROR]
    return out.graph


def test_patterns_and_templates_registered() -> None:
    reg = discover(entry_points=False)
    pats = {k for p in reg.services_named("topology.patterns") for k in p()}
    tpls = {k for p in reg.services_named("topology.templates") for k in p()}
    assert {BOOST, BUCK_BOOST} <= pats and {BOOST, BUCK_BOOST} <= tpls


def test_boost_pattern_roles_and_rails() -> None:
    matches = BoostFamilyPattern(BOOST).match(_graph(BOOST_NETS, BOOST_PARTS), BOOST_PARTS)
    assert matches, "boost stage not found"
    m = matches[0]
    assert m.rails == {"vin": "VIN", "sw": "SW", "vout": "VOUT", "gnd": "GND"}
    assert m.roles["low_side_switch"] == ("Q1",) and m.roles["catch_diode"] == ("D1",)
    assert m.roles["output_cap"] == ("C2", "C3") and m.roles["input_cap"] == ("C1",)
    assert m.roles["controller"] == ("U1",) and not m.unmet
    proposal = BoostFamilyPattern(BOOST).propose(m, BOOST_PARTS)
    by_ref = {a.refdes: a.role for a in proposal.assignments}
    assert by_ref["R1"] == "other" and by_ref["L1"] == "inductor"


def test_buck_boost_pattern() -> None:
    matches = BoostFamilyPattern(BUCK_BOOST).match(_graph(BB_NETS, BB_PARTS), BB_PARTS)
    m = matches[0]
    assert m.rails == {"vin": "VIN", "sw": "SW", "vout": "VNEG", "gnd": "GND"}
    assert m.roles["high_side_switch"] == ("Q1",) and m.roles["catch_diode"] == ("D1",)
    assert not m.unmet
    # a buck-boost netlist is not a boost: no switch from sw to ground
    assert not BoostFamilyPattern(BOOST).match(_graph(BB_NETS, BB_PARTS), BB_PARTS)


def test_boost_through_m2(clock: FixedClock) -> None:
    roles = RoleMap(
        roles={
            "inductor": ("L1",),
            "low_side_switch": ("Q1",),
            "catch_diode": ("D1",),
            "output_cap": ("C2", "C3"),
            "input_cap": ("C1",),
        },
        rails={"vin": "VIN", "sw": "SW", "vout": "VOUT", "gnd": "GND"},
    )
    spec = ConverterSpec(vin_min=3.3, vin_max=4.2, vout=5, iout_max=2, fsw=1e6, t_ambient=25)
    parts = [
        p.model_copy(update={"value_si": 2.2e-6}) if p.refdes == "L1" else p for p in BOOST_PARTS
    ]
    out = compute_template_stress(BoostFamilyTemplate(BOOST), spec, parts, roles, clock)
    assert out.params["vd"] == 0.4 and out.params["synchronous"] == 0.0
    got = {(s.part_id, s.param, s.scenario): s.value for s in out.stress}
    # Case B2 of test_equations (Vin 3.3, Vout 5, Iout 2, 1 MHz, 2.2 uH, Vf 0.4)
    assert got[(1, "i_peak", "vin_min")] == pytest.approx(3.564394, rel=1e-3)
    assert got[(2, "i_rms", "vin_min")] == pytest.approx(2.043604, rel=1e-3)
    assert got[(2, "v_peak", "vin_min")] == pytest.approx(5.4, rel=1e-3)
    assert got[(3, "i_rms", "vin_min")] == pytest.approx(2.561793, rel=1e-3)
    assert got[(5, "i_rms", "vin_min")] == pytest.approx(1.600870 / 2, rel=1e-3)  # 2 caps share
    assert got[(1, "p_loss", "vin_min")] == pytest.approx(3.277057**2 * 0.05, rel=1e-3)
    assert out.prompts == []


def test_boost_template_needs_vd_and_rejects_step_down() -> None:
    t = BoostFamilyTemplate(BOOST)
    base = {"vin_min": 5, "vin_max": 9, "vout": 12, "iout_max": 1, "fsw": 5e5, "t_ambient": 25}
    out = t.compute_full({**base, "L": 10e-6, "synchronous": 0.0})
    assert "vd" in out.needs and "catch_diode" in out.stress
    sync = t.compute_full({**base, "L": 10e-6, "rds_hs": 0.02, "rds_ls": 0.03})
    assert "high_side_switch" in sync.stress and "catch_diode" not in sync.stress
    assert any(s.param == "p_loss" for s in sync.stress["low_side_switch"])
    bad = t.compute_full({**base, "vin_max": 15, "L": 10e-6})
    assert any(d.code == "TEMPLATE_INVALID_INPUT" for d in bad.diagnostics) and not bad.stress
