from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from dfr.core.contracts import (
    ClassifiedBom,
    NetKind,
    Part,
    PartClass,
    PinFunctionProvenance,
    Rating,
    RatingProvenance,
    Severity,
)
from dfr.core.db.repos import DesignRepo, NetlistRepo, PartRepo
from dfr.core.ports import FixedClock
from dfr.modules.m1_bom.catalog import CatalogRepo
from dfr.modules.m1_bom.join import join_netlist, prune_dnp
from dfr.modules.m1_bom.netlist import default_parsers, pick_parser
from dfr.modules.m1_bom.netlist.service import import_netlist
from dfr.modules.m1_bom.nets import classify_net, is_auto_generated, normalize_net_name
from dfr.modules.m1_bom.persist import persist_design
from dfr.modules.m1_bom.pins import apply_user_pinout, resolve_pin_functions
from dfr.modules.m1_bom.service import import_bom
from tests.conftest import FIXTURES

NETLIST = FIXTURES / "design_c" / "design_c_protel.net"
BOMDOC = FIXTURES / "design_c" / "design_c.BomDoc"


@pytest.fixture(scope="module")
def design_c():
    net = import_netlist(NETLIST.read_bytes(), "design_c_protel.net")
    _, bom = import_bom(BOMDOC.read_bytes(), "design_c.BomDoc")
    return net, bom


# ----------------------------------------------------------------------------- parser (NET-02)


def test_protel_parse_counts(design_c) -> None:
    net, _ = design_c
    g = net.graph
    assert g.source_format == "altium_protel" and len(g.source_hash) == 64
    assert len(g.components) == 28
    assert len(g.nets) == 19
    assert len(g.pins) == 84
    assert {(p.refdes, p.pin_id) for p in g.pins_on_net("NetC3_1")} == {
        ("C3", "1"),
        ("L1", "1"),
        ("U3", "7"),
    }
    assert sorted((p.pin_id for p in g.pins_of("U3")), key=int) == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "13",
    ]
    assert next(c for c in g.components if c.refdes == "P1").comment == "Copy of MHDR1X3"
    assert [d.code for d in net.diagnostics] == ["NET_EMPTY_NET"]
    assert net.diagnostics[0].line_no == 344


def test_pick_parser_by_content_and_extension() -> None:
    data = NETLIST.read_bytes()
    assert pick_parser(data, "x.txt", default_parsers()).id == "altium_protel"
    assert pick_parser(b"nope", "x.net", default_parsers()).id == "altium_protel"
    assert pick_parser(b"nope", "x.xyz", default_parsers()) is None
    assert import_netlist(b"nope", "x.xyz").diagnostics[0].code == "NET_UNKNOWN_FORMAT"


def test_protel_messy_input_reports_line_numbers() -> None:
    text = (
        "[\r\nR1\r\nRES0603\r\nABC\r\n\r\n\r\n\r\n]\r\n"
        "[\r\nR1\r\nRES0603\r\nABC\r\n\r\n\r\n\r\n]\r\n"  # duplicate
        "[\r\n\r\n]\r\n"  # no refdes
        "garbage\r\n"
        "(\r\nN1\r\nR1-1\r\nbadnode\r\nR9-2\r\n)\r\n"
        "(\r\nN1\r\nR1-2\r\n)\r\n"  # duplicate net
        "(\r\nN2\r\n"  # unterminated
    )
    res = import_netlist(text.encode("ascii"), "m.net")
    codes = sorted(d.code for d in res.diagnostics)
    assert codes == sorted(
        [
            "NET_DUPLICATE_REFDES",
            "NET_COMPONENT_NO_REFDES",
            "NET_UNPARSED_LINE",
            "NET_BAD_NODE",
            "NET_PIN_UNKNOWN_COMPONENT",
            "NET_DUPLICATE_NET",
            "NET_UNTERMINATED_BLOCK",
        ]
    )
    assert all(d.line_no for d in res.diagnostics if d.code != "NET_PIN_UNKNOWN_COMPONENT")
    assert len(res.graph.components) == 1 and len(res.graph.nets) == 1


# ----------------------------------------------------------------------------- nets (NET-04)


@pytest.mark.parametrize(
    ("name", "norm", "kind"),
    [
        ("GND", "GND", NetKind.GROUND),
        ("AGND", "AGND", NetKind.GROUND),
        ("PGND1", "PGND1", NetKind.GROUND),
        ("0", "0", NetKind.GROUND),
        ("/VIN", "VIN", NetKind.POWER),
        ("/sheet1/VCC_3V3", "VCC_3V3", NetKind.POWER),
        ("+5V", "+5V", NetKind.POWER),
        ("12V", "12V", NetKind.POWER),
        ("Buck_in", "Buck_in", NetKind.POWER),
        ("Buck_out", "Buck_out", NetKind.POWER),
        ("VCC_int", "VCC_int", NetKind.POWER),
        ("Net-(C1-Pad1)", "Net-(C1-Pad1)", NetKind.SIGNAL),
        ("NetC3_1", "NetC3_1", NetKind.SIGNAL),
        ("SDA", "SDA", NetKind.SIGNAL),
        ("RESET_N", "RESET_N", NetKind.SIGNAL),
    ],
)
def test_net_rules(name: str, norm: str, kind: NetKind) -> None:
    assert normalize_net_name(name) == norm
    assert classify_net(norm) is kind


def test_auto_generated() -> None:
    assert is_auto_generated("NetC3_1") and is_auto_generated("Net-(C1-Pad1)")
    assert not is_auto_generated("VIN")


def test_design_c_net_kinds(design_c) -> None:
    net, _ = design_c
    kinds = {n.name: n.kind for n in net.graph.nets}
    assert kinds["GND"] is NetKind.GROUND
    assert kinds["Buck_in"] is NetKind.POWER and kinds["Buck_out"] is NetKind.POWER
    assert kinds["NetC3_1"] is NetKind.SIGNAL


# ----------------------------------------------------------------------------- join (NET-03/05/10)


def test_join_by_mpn_zero_unmatched(design_c) -> None:
    net, bom = design_c
    j = join_netlist(net.graph, bom)
    assert len(j.parts) == 28
    assert j.join.netlist_only == [] and j.join.bom_only == []
    by = {p.refdes: p for p in j.parts}
    assert by["C5"].mpn == by["C6"].mpn == "GCM32ER71A226KE12L"
    assert by["C5"].value_si == pytest.approx(22e-6) and by["C6"].ratings.get("v_rated").value == 10
    assert by["L1"].part_class is PartClass.INDUCTOR and by["L1"].ratings.get(
        "dcr"
    ).value == pytest.approx(0.08635)
    assert by["U3"].subtype == "switching_regulator"
    assert by["R3"].subtype == "sense"
    assert by["P1"].part_class is PartClass.CONNECTOR
    assert all(p.class_confidence >= 0.9 for p in j.parts), [
        (p.refdes, p.class_confidence) for p in j.parts if p.class_confidence < 0.9
    ]
    assert not [d for d in j.diagnostics if d.severity is Severity.ERROR]


def test_join_by_mpn_reports_unmatched(design_c) -> None:
    net, bom = design_c
    smaller = bom.model_copy(
        update={
            "templates_by_mpn": {k: v for k, v in bom.templates_by_mpn.items() if k != "INA238"}
        }
    )
    j = join_netlist(net.graph, smaller)
    assert sorted(j.join.netlist_only) == ["U1", "U2"]
    assert {p.refdes: p.part_class for p in j.parts if p.refdes in ("U1", "U2")} == {
        "U1": PartClass.IC,
        "U2": PartClass.IC,
    }
    assert all(p.class_confidence <= 0.5 for p in j.parts if p.refdes in ("U1", "U2"))
    assert sum(d.code == "JOIN_NETLIST_ONLY" for d in j.diagnostics) == 2


def test_join_by_refdes_with_mismatches() -> None:
    text = (
        "[\r\nC1\r\nCAP0603\r\nX\r\n\r\n\r\n\r\n]\r\n"
        "[\r\nc2_1\r\nCAP0603\r\nY\r\n\r\n\r\n\r\n]\r\n"
        "[\r\nTP1\r\nTP\r\n\r\n\r\n\r\n\r\n]\r\n"
        "(\r\nN\r\nC1-1\r\nc2_1-1\r\n)\r\n"
    )
    g = import_netlist(text.encode(), "t.net").graph
    bom = ClassifiedBom(
        parts=[
            Part(refdes="C1", part_class=PartClass.CAPACITOR, value_si=1e-6),
            Part(refdes="C2", part_class=PartClass.CAPACITOR, value_si=2e-6),
            Part(refdes="R9", part_class=PartClass.RESISTOR),  # BOM only
        ]
    )
    j = join_netlist(g, bom)
    by = {p.refdes: p for p in j.parts}
    assert by["c2_1"].value_si == 2e-6  # suffix/case tolerant
    assert by["TP1"].part_class is PartClass.TEST_POINT
    assert j.join.netlist_only == ["TP1"] and j.join.bom_only == ["R9"]
    assert "R9" in by  # kept, without connectivity
    assert len(j.join.matched) == 4


def test_prune_dnp_removes_pins(design_c) -> None:
    net, bom = design_c
    j = join_netlist(net.graph, bom)
    parts = [p.model_copy(update={"dnp": True}) if p.refdes == "R4" else p for p in j.parts]
    pruned = prune_dnp(net.graph, parts)
    assert "R4" not in {c.refdes for c in pruned.components}
    assert not pruned.pins_of("R4")
    assert len(pruned.pins) == len(net.graph.pins) - 2
    assert prune_dnp(net.graph, j.parts) is net.graph  # no DNP: unchanged object


# ----------------------------------------------------------------------------- pins (NET-06)


def test_pin_resolution_requests_unknown_pinouts(design_c) -> None:
    net, bom = design_c
    j = join_netlist(net.graph, bom)
    r = resolve_pin_functions(net.graph, j.parts)
    assert sorted(r.unresolved_refdes) == ["D1", "D2", "D3", "Q1", "Q2", "U1", "U2", "U3"]
    u3 = next(q for q in r.requests if q.refdes == "U3")
    assert u3.mpn == "LM63635CC3QDRRRQ1"
    assert u3.pin_ids == ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "13")
    terminals = [p for p in r.pins if p.function == "terminal"]
    assert len(terminals) == 34  # C1..C8 (16) + R1..R7 (14) + L1 (2) + F1 (2)
    assert all(p.function_provenance is PinFunctionProvenance.SEED for p in terminals)
    assert len(r.pins) == len(net.graph.pins)


def test_library_pinmap_resolves_and_user_answer_is_saved(
    design_c,
    session: Session,
    clock: FixedClock,
) -> None:
    net, bom = design_c
    j = join_netlist(net.graph, bom)
    catalog = CatalogRepo(session, clock)
    q1_map = {"1": "gate", "2": "drain", "3": "source"}
    catalog.upsert(mpn="IPD90P03P4L-04", part_class=PartClass.TRANSISTOR, pinmap=q1_map)

    r = resolve_pin_functions(
        net.graph, j.parts, catalog, inferred={"U3": {"7": "sw", "6": "boot"}}
    )
    assert "Q1" not in r.unresolved_refdes
    q1 = {p.pin_id: p.function for p in r.pins if p.refdes == "Q1"}
    assert q1 == q1_map
    u3 = next(q for q in r.requests if q.refdes == "U3")
    assert u3.inferred == {"7": "sw", "6": "boot"}  # prefill only
    assert all(p.function is None for p in r.pins if p.refdes == "U3")  # never applied

    u3_part = next(p for p in j.parts if p.refdes == "U3")
    answer = {pid: "gnd" for pid in u3.pin_ids}
    answer.update({"7": "sw", "6": "boot", "1": "vin", "2": "vin", "8": "vout_sense"})
    r2 = apply_user_pinout(r, "U3", answer, catalog, u3_part)
    assert "U3" not in r2.unresolved_refdes and not [q for q in r2.requests if q.refdes == "U3"]
    assert {p.pin_id: p.function for p in r2.pins if p.refdes == "U3"}["7"] == "sw"
    assert all(
        p.function_provenance is PinFunctionProvenance.USER for p in r2.pins if p.refdes == "U3"
    )

    # Re-importing asks nothing for U3 (NET-06).
    r3 = resolve_pin_functions(net.graph, j.parts, catalog)
    assert "U3" not in r3.unresolved_refdes


# ----------------------------------------------------------------------------- persist


def test_persist_design_round_trip(design_c, session: Session, clock: FixedClock) -> None:
    net, bom = design_c
    j = join_netlist(net.graph, bom)
    r = resolve_pin_functions(net.graph, j.parts)
    design = DesignRepo(session, clock).create("Design C", topology_template="buck_integrated")
    stored = persist_design(
        session,
        clock,
        design_id=design.id,
        parts=j.parts,
        nets=net.graph.nets,
        pins=r.pins,
        graph=net.graph,
        bom_hash="bomhash",
    )
    assert len(stored.part_ids) == 28 and len(stored.net_ids) == 19
    version = DesignRepo(session, clock).latest_version(design.id)
    assert (
        version.netlist_hash == net.graph.source_hash and version.netlist_format == "altium_protel"
    )
    parts = PartRepo(session).for_version(stored.design_version_id)
    assert len(parts) == 28
    l1 = next(p for p in parts if p.refdes == "L1")
    assert l1.ratings.get("dcr").provenance is RatingProvenance.BOM_DESCRIPTION
    nets = NetlistRepo(session)
    sw = nets.net_by_name(stored.design_version_id, "NetC3_1")
    assert {(p.refdes, p.pin_id) for p in nets.pins_on_net(sw.id)} == {
        ("C3", "1"),
        ("L1", "1"),
        ("U3", "7"),
    }
    assert len(nets.pins_for_part(stored.part_ids["U3"])) == 12
    assert isinstance(l1.ratings.get("i_rated"), Rating)
