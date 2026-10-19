"""REC-01..08, REC-10, S8: Design C golden role map and negative cases."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from dfr.core.contracts import (
    NetlistGraph,
    Part,
    PartClass,
    ProposalProvenance,
    RoleEdit,
    StageStatus,
)
from dfr.core.db.repos import DesignRepo, StageRepo
from dfr.core.ports import FixedClock
from dfr.core.registry import discover
from dfr.modules.m1_bom.join import join_netlist, prune_dnp
from dfr.modules.m1_bom.netlist.service import import_netlist
from dfr.modules.m1_bom.persist import persist_design
from dfr.modules.m1_bom.pins import resolve_pin_functions
from dfr.modules.m1_bom.service import import_bom
from dfr.modules.m12_topology.service import (
    apply_edits,
    available_patterns,
    check_staleness,
    confirm_roles,
    match_topology,
    prefill_from_stale,
    role_map_for,
)
from dfr.topologies.buck.inference import infer_pin_functions
from dfr.topologies.buck.pattern import BuckPattern
from tests.conftest import FIXTURES

NETLIST = FIXTURES / "design_c" / "design_c_protel.net"
BOMDOC = FIXTURES / "design_c" / "design_c.BomDoc"

GOLDEN_ROLES = {
    "U3": "ic",
    "L1": "inductor",
    "C5": "output_cap",
    "C6": "output_cap",
    "C1": "input_cap",
    "C2": "input_cap",
    "C3": "boot_cap",
}
GOLDEN_RAILS = {"vin": "Buck_in", "sw": "NetC3_1", "vout": "Buck_out", "gnd": "GND"}
GOLDEN_U3_PINS = {
    "1": "vin",
    "2": "vin",
    "3": "gnd",
    "4": "other",
    "5": "gnd",
    "6": "boot",
    "7": "sw",
    "8": "vout_sense",
    "9": "other",
    "10": "other",
    "11": "gnd",
    "13": "gnd",
}


@pytest.fixture(scope="module")
def design_c() -> tuple[NetlistGraph, list[Part]]:
    graph = import_netlist(NETLIST.read_bytes(), "d.net").graph
    _, bom = import_bom(BOMDOC.read_bytes(), "d.BomDoc")
    return graph, join_netlist(graph, bom).parts


@pytest.fixture(scope="module")
def patterns():
    reg = discover(entry_points=False)
    return available_patterns(reg.services_named("topology.patterns"))


def test_patterns_discovered_from_topology_folder(patterns) -> None:
    """REC-02: patterns load through the registry, M12 imports no topology folder."""
    assert set(patterns) >= {"buck", "buck_integrated"}


def test_design_c_golden_role_map(design_c, patterns) -> None:
    """REC-03, REC-04, REC-10, S8."""
    graph, parts = design_c
    out = match_topology(graph, parts, "buck_integrated", patterns)
    assert out.matched
    best = out.matches[0]
    assert best.rails == GOLDEN_RAILS
    assert best.unmet == []
    assert best.confidence >= 0.7
    roles = {a.refdes: a.role for a in out.proposal.assignments}
    assert {k: roles[k] for k in GOLDEN_ROLES} == GOLDEN_ROLES
    others = {r for r, role in roles.items() if role == "other"}
    assert others == set(p.refdes for p in parts) - set(GOLDEN_ROLES)
    assert all(a.provenance is ProposalProvenance.PROPOSED for a in out.proposal.assignments)
    assert any(a.evidence.startswith("L1: NetC3_1 -> Buck_out") for a in out.proposal.assignments)
    assert not [d for d in out.diagnostics if d.code in ("TOPO_NO_MATCH", "TOPO_LOW_CONFIDENCE")]


def test_decoy_candidate_ranks_last(design_c) -> None:
    graph, parts = design_c
    matches = BuckPattern("integrated").match(graph, parts)
    assert len(matches) == 2
    assert matches[0].rails["sw"] == "NetC3_1"
    assert matches[1].confidence < 0.4 and "inductor_to_vout" in matches[1].unmet


def test_pin_inference_matches_prd_example(design_c, patterns) -> None:
    graph, parts = design_c
    out = match_topology(
        graph,
        parts,
        "buck_integrated",
        patterns,
        inference={"buck_integrated": infer_pin_functions},
    )
    assert out.inferred_pins["U3"] == GOLDEN_U3_PINS
    # Inference feeds the pinout request as prefill only (NET-06).
    res = resolve_pin_functions(graph, parts, inferred=out.inferred_pins)
    u3 = next(q for q in res.requests if q.refdes == "U3")
    assert u3.inferred == GOLDEN_U3_PINS
    assert all(p.function is None for p in res.pins if p.refdes == "U3")


def test_no_match_without_inductor_lists_unmet(design_c, patterns) -> None:
    """REC-05."""
    graph, parts = design_c
    no_l = [p for p in parts if p.refdes != "L1"]
    graph2 = graph.model_copy(update={"pins": [p for p in graph.pins if p.refdes != "L1"]})
    out = match_topology(graph2, no_l, "buck_integrated", patterns)
    assert not out.matched and out.matches == []
    assert out.diagnostics[0].code == "TOPO_NO_MATCH"


def test_dnp_inductor_is_pruned_before_matching(design_c, patterns) -> None:
    graph, parts = design_c
    parts2 = [p.model_copy(update={"dnp": True}) if p.refdes == "L1" else p for p in parts]
    out = match_topology(prune_dnp(graph, parts2), parts2, "buck_integrated", patterns)
    assert not out.matched


def test_discrete_variant_does_not_match_integrated_board(design_c, patterns) -> None:
    graph, parts = design_c
    out = match_topology(graph, parts, "buck", patterns)
    assert not out.matched and out.diagnostics[0].code == "TOPO_NO_MATCH"


def test_unknown_pattern_is_diagnostic(design_c, patterns) -> None:
    graph, parts = design_c
    out = match_topology(graph, parts, "flyback", patterns)
    assert not out.matched and out.diagnostics[0].code == "TOPO_UNKNOWN_PATTERN"


def test_bom_hints_conflict_is_warning_not_decisive(design_c, patterns) -> None:
    graph, parts = design_c
    out = match_topology(
        graph, parts, "buck_integrated", patterns, bom_hints={"U3": ("boost", "step-up")}
    )
    assert out.matched  # still matches
    assert any(d.code == "TOPO_HINT_CONFLICT" for d in out.diagnostics)
    out2 = match_topology(graph, parts, "buck_integrated", patterns, bom_hints={"U3": ("buck",)})
    assert any(d.code == "TOPO_HINT_AGREES" for d in out2.diagnostics)


def test_discrete_buck_synthetic() -> None:
    """Discrete variant on a hand-built synchronous buck: Q1 high, Q2 low, U1 controller."""
    text = "".join(
        f"[\r\n{r}\r\nFP\r\nX\r\n\r\n\r\n\r\n]\r\n"
        for r in ("Q1", "Q2", "L1", "C1", "C2", "U1", "R1")
    ) + (
        "(\r\nVIN\r\nQ1-1\r\nC1-1\r\nU1-1\r\n)\r\n"
        "(\r\nSW\r\nQ1-3\r\nQ2-1\r\nL1-1\r\nU1-5\r\n)\r\n"
        "(\r\nVOUT\r\nL1-2\r\nC2-1\r\nR1-1\r\n)\r\n"
        "(\r\nGND\r\nQ2-3\r\nC1-2\r\nC2-2\r\nU1-2\r\nR1-2\r\n)\r\n"
        "(\r\nHG\r\nQ1-2\r\nU1-3\r\n)\r\n"
        "(\r\nLG\r\nQ2-2\r\nU1-4\r\n)\r\n"
    )
    graph = import_netlist(text.encode(), "d.net").graph
    parts = [
        Part(refdes="Q1", part_class=PartClass.TRANSISTOR, subtype="mosfet_n"),
        Part(refdes="Q2", part_class=PartClass.TRANSISTOR, subtype="mosfet_n"),
        Part(refdes="L1", part_class=PartClass.INDUCTOR, value_si=4.7e-6),
        Part(refdes="C1", part_class=PartClass.CAPACITOR),
        Part(refdes="C2", part_class=PartClass.CAPACITOR),
        Part(refdes="U1", part_class=PartClass.IC),
        Part(refdes="R1", part_class=PartClass.RESISTOR, value_si=10e3),
    ]
    m = BuckPattern("discrete").match(graph, parts)[0]
    assert m.unmet == []
    assert m.rails == {"sw": "SW", "vout": "VOUT", "vin": "VIN", "gnd": "GND"}
    assert m.roles["high_side_switch"] == ("Q1",) and m.roles["low_side_switch"] == ("Q2",)
    assert m.roles["controller"] == ("U1",)
    assert m.roles["input_cap"] == ("C1",) and m.roles["output_cap"] == ("C2",)
    assert m.confidence > 0.7  # all rail names agree too
    inferred = infer_pin_functions(m, graph, parts)
    assert inferred["Q1"] == {"1": "drain", "2": "gate", "3": "source"}
    assert inferred["Q2"] == {"1": "drain", "2": "gate", "3": "source"}


def test_sense_resistor_between_inductor_and_vout() -> None:
    text = "".join(
        f"[\r\n{r}\r\nFP\r\nX\r\n\r\n\r\n\r\n]\r\n" for r in ("U1", "L1", "R1", "C1", "C2")
    ) + (
        "(\r\nVIN\r\nU1-1\r\nC1-1\r\n)\r\n(\r\nSW\r\nU1-2\r\nL1-1\r\n)\r\n"
        "(\r\nLOUT\r\nL1-2\r\nR1-1\r\n)\r\n(\r\nVOUT\r\nR1-2\r\nC2-1\r\n)\r\n"
        "(\r\nGND\r\nU1-3\r\nC1-2\r\nC2-2\r\n)\r\n"
    )
    graph = import_netlist(text.encode(), "d.net").graph
    parts = [
        Part(refdes="U1", part_class=PartClass.IC),
        Part(refdes="L1", part_class=PartClass.INDUCTOR),
        Part(refdes="R1", part_class=PartClass.RESISTOR, value_si=0.01),
        Part(refdes="C1", part_class=PartClass.CAPACITOR),
        Part(refdes="C2", part_class=PartClass.CAPACITOR),
    ]
    m = BuckPattern("integrated").match(graph, parts)[0]
    assert m.rails["vout"] == "VOUT" and m.roles["sense_resistor"] == ("R1",)
    assert m.roles["output_cap"] == ("C2",)


# ----------------------------------------------------------------------------- confirm / persist


def test_edit_confirm_persist_and_staleness(
    design_c,
    patterns,
    session: Session,
    clock: FixedClock,
) -> None:
    """REC-06, REC-07, REC-08 path through the database."""
    graph, parts = design_c
    design = DesignRepo(session, clock).create("Design C", topology_template="buck_integrated")
    stored = persist_design(
        session,
        clock,
        design_id=design.id,
        parts=parts,
        nets=graph.nets,
        pins=resolve_pin_functions(graph, parts).pins,
        graph=graph,
        bom_hash="b",
    )
    out = match_topology(graph, parts, "buck_integrated", patterns)
    edits = [RoleEdit(refdes="R3", role="sense_resistor", rail="vout")]
    edited = apply_edits(out.proposal, edits)
    assert (
        next(a for a in edited.assignments if a.refdes == "R3").provenance
        is ProposalProvenance.USER
    )

    stage = confirm_roles(
        session,
        clock,
        design_version_id=stored.design_version_id,
        proposal=out.proposal,
        edits=edits,
        netlist_hash=graph.source_hash,
    )
    assert stage.status is StageStatus.CONFIRMED
    assert {a.provenance for a in stage.assignments} == {ProposalProvenance.USER}
    rm = role_map_for(session, clock, stage.id)
    assert rm.parts_with_role("output_cap") == ("C5", "C6")
    assert rm.parts_with_role("sense_resistor") == ("R3",)
    assert rm.rails == GOLDEN_RAILS

    assert not check_staleness(session, clock, stage, graph.source_hash)
    assert check_staleness(session, clock, stage, "different")
    stale = StageRepo(session, clock).get(stage.id)
    assert stale.status is StageStatus.STALE

    fresh = match_topology(graph, parts, "buck_integrated", patterns).proposal
    carried = prefill_from_stale(stale, fresh)
    r3 = next(a for a in carried.assignments if a.refdes == "R3")
    assert r3.role == "sense_resistor" and "carried from stale stage" in r3.evidence
