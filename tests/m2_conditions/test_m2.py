from __future__ import annotations

from collections.abc import Mapping

import pytest

from dfr.core.contracts import (
    ConverterSpec,
    Diagnostic,
    Part,
    PartClass,
    PromptOrigin,
    Rating,
    RatingProvenance,
    RatingSet,
    RoleMap,
    Severity,
    Source,
    Stat,
    StressSpec,
    Tier,
    ValuePrompt,
)
from dfr.core.extension import TopologyTemplate
from dfr.core.ports import FixedClock
from dfr.modules.m2_conditions.infer import infer_passives
from dfr.modules.m2_conditions.service import answer_prompt, compute_template_stress, manual_stress
from tests.conftest import T0


def part(
    refdes: str, cls: PartClass, value: float | None = None, pid: int = 0, **ratings: float
) -> Part:
    units = {"dcr": "ohm", "esr": "ohm", "rds_on": "ohm", "eta": "", "v_rated": "V"}
    return Part(
        id=pid or abs(hash(refdes)) % 10000 + 1,
        refdes=refdes,
        part_class=cls,
        value_si=value,
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit=units.get(k, ""), provenance=RatingProvenance.SEED)
                for k, v in ratings.items()
            }
        ),
    )


PARTS = [
    part("L1", PartClass.INDUCTOR, 4.7e-6, 1, dcr=0.020),
    part("C5", PartClass.CAPACITOR, 22e-6, 2, esr=0.005),
    part("C6", PartClass.CAPACITOR, 22e-6, 3, esr=0.005),
    part("C7", PartClass.CAPACITOR, 100e-6, 4),  # no ESR
    part("C1", PartClass.CAPACITOR, 10e-6, 5),
    part("U3", PartClass.IC, None, 6),
]
ROLES = RoleMap(
    roles={
        "inductor": ("L1",),
        "output_cap": ("C5", "C6", "C7"),
        "input_cap": ("C1",),
        "ic": ("U3",),
    },
    rails={"sw": "SW", "vout": "VOUT", "vin": "VIN", "gnd": "GND"},
)
SPEC = ConverterSpec(vin_min=24, vin_max=24, vout=5, iout_max=3, fsw=500e3, t_ambient=40)


# ----------------------------------------------------------------------------- infer (OPC-12)


def test_infer_design_a_like() -> None:
    inf = infer_passives(PARTS, ROLES)
    assert inf.values["L"].value == pytest.approx(4.7e-6) and inf.values[
        "L"
    ].contributing_refdes == ("L1",)
    assert inf.values["dcr"].value == pytest.approx(0.020)
    assert inf.values["cout"].value == pytest.approx(144e-6)
    assert inf.values["cout"].contributing_refdes == ("C5", "C6", "C7")
    assert inf.values["esr_eq"].value == pytest.approx(0.0025)  # two 5 mohm in parallel; C7 unknown
    assert "missing" in (inf.values["esr_eq"].note or "")
    assert all(v.provenance == "bom" for v in inf.values.values())


def test_infer_override_wins_and_is_marked() -> None:
    inf = infer_passives(PARTS, ROLES, overrides={"cout": 100e-6})
    assert inf.values["cout"].value == 100e-6
    assert inf.values["cout"].provenance == "user" and inf.values["cout"].note == "overrides BOM"
    assert inf.values["L"].provenance == "bom"


def test_infer_errors_block_with_named_part() -> None:
    from dfr.core.diagnostics import DiagnosticSink

    sink = DiagnosticSink("t")
    bad = [p.model_copy(update={"value_si": None}) if p.refdes == "L1" else p for p in PARTS]
    inf = infer_passives(bad, ROLES, sink=sink)
    assert "L" not in inf.values
    assert any(d.code == "INFER_L_MISSING" and "L1" in d.message for d in sink)

    sink2 = DiagnosticSink("t")
    two = RoleMap(roles={**ROLES.roles, "inductor": ("L1", "L2")})
    infer_passives(PARTS, two, sink=sink2)
    assert any(d.code == "INFER_L_AMBIGUOUS" for d in sink2)

    sink3 = DiagnosticSink("t")
    infer_passives(PARTS, RoleMap(), sink=sink3)
    assert {d.code for d in sink3} >= {"INFER_L_NO_ROLE", "INFER_COUT_NO_ROLE"}


# ----------------------------------------------------------------------------- template binding


class FakeTemplate(TopologyTemplate):
    """Minimal template: one row per role, exercises the ABC-only path and `needs`."""

    id = "fake"
    version = "9.9"
    pattern_id = "fake"
    required_inputs = ("L",)
    roles = ("inductor", "output_cap", "ic")

    def validity_checks(self, params: Mapping[str, float]) -> list[Diagnostic]:
        return (
            [] if "L" in params else [Diagnostic(code="X", severity=Severity.ERROR, message="no L")]
        )

    def compute(self, params: Mapping[str, float]) -> dict[str, list[StressSpec]]:
        return {
            "inductor": [
                StressSpec(param="i_rms", value=3.0, unit="A", stat=Stat.RMS, scenario="vin_max")
            ],
            "output_cap": [
                StressSpec(param="i_rms", value=0.6, unit="A", stat=Stat.RMS, scenario="vin_max")
            ],
            "ic": [
                StressSpec(
                    param="v_peak",
                    value=params["vin_max"],
                    unit="V",
                    stat=Stat.PEAK,
                    scenario="vin_max",
                )
            ],
        }


def test_compute_template_stress_binds_parts_and_splits_shared_rows(clock: FixedClock) -> None:
    out = compute_template_stress(FakeTemplate(), SPEC, PARTS, ROLES, clock)
    by = {(s.part_id, s.param): s for s in out.stress}
    assert by[(1, "i_rms")].value == 3.0
    assert by[(2, "i_rms")].value == pytest.approx(0.2) and "1/3" in (by[(2, "i_rms")].note or "")
    assert by[(6, "v_peak")].value == 24
    s = by[(1, "i_rms")]
    assert s.source is Source.EQUATION and s.tier is Tier.T1 and s.tool == "topology.fake@9.9"
    assert s.tool_version == "9.9" and s.timestamp == T0
    assert any(d.code == "M2_EQUAL_SHARING" for d in out.diagnostics)
    assert out.params["L"] == pytest.approx(4.7e-6) and out.params["vin_max"] == 24
    assert out.prompts == []


# ----------------------------------------------------------------------------- manual / prompts


def test_manual_and_prompt_answers(clock: FixedClock) -> None:
    m = manual_stress(2, "v_dc", 5.0, "V", Stat.DC, clock, pinned=True, note="from schematic")
    assert m.source is Source.MANUAL and m.tier is Tier.T1 and m.pinned and m.tool == "manual"

    prompt = ValuePrompt(
        id=7,
        part_id=6,
        param="p_loss",
        stat="avg",
        scenario="vin_max",
        reason="r",
        how_to_obtain="h",
        origin=PromptOrigin.M2,
    )
    a = answer_prompt(prompt, 0.8, "W", Source.MEASURED, "bench, Fluke 287", clock)
    assert a.tier is Tier.T2 and a.source is Source.MEASURED and a.tool == "prompt:bench, Fluke 287"
    assert a.part_id == 6 and a.stat is Stat.AVG and a.note == "r"
    with pytest.raises(ValueError, match="simulated"):
        answer_prompt(prompt, 1.0, "W", Source.MANUAL, "", clock)
    with pytest.raises(ValueError, match="no part"):
        answer_prompt(
            prompt.model_copy(update={"part_id": None}), 1.0, "W", Source.MEASURED, "", clock
        )
