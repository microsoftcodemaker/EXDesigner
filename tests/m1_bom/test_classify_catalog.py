from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from dfr.core.contracts import BomImportResult, PartClass, Rating, RatingProvenance, RawPart
from dfr.core.ports import FixedClock
from dfr.modules.m1_bom.catalog import CatalogRepo, merge_ratings, seed_ratings
from dfr.modules.m1_bom.classify import classify
from dfr.modules.m1_bom.description import parse_description
from dfr.modules.m1_bom.service import classify_bom, read_bom


@pytest.mark.parametrize(
    ("refdes", "desc", "cls", "subtype"),
    [
        ("R1", "RES SMD 2K OHM 1% 1/16W 0402", PartClass.RESISTOR, "chip"),
        ("C1", "10uF 25V X7R", PartClass.CAPACITOR, "ceramic"),
        ("C2", "100uF 35V electrolytic CP_Radial", PartClass.CAPACITOR, "aluminum_electrolytic"),
        ("L1", "10uH shielded power inductor", PartClass.INDUCTOR, "power"),
        ("FB1", "ferrite bead 600R", PartClass.INDUCTOR, "bead"),
        ("D1", "SS34 Schottky", PartClass.DIODE, "schottky"),
        ("D2", "BZX384B10", PartClass.DIODE, "zener"),
        ("Q1", "NMOS 60V 30A", PartClass.TRANSISTOR, "mosfet_n"),
        ("U1", "LM5145 buck controller", PartClass.IC, "switching_regulator"),
        ("J1", "Header, 3-Pin", PartClass.CONNECTOR, "header"),
        ("F1", "fuse 2A", PartClass.FUSE, None),
        ("Y1", "crystal 16MHz", PartClass.CRYSTAL, None),
        ("TP1", None, PartClass.TEST_POINT, None),
        ("SW1", "tactile switch", PartClass.SWITCH, None),
        ("T1", "flyback transformer", PartClass.TRANSFORMER, None),
        ("LED1", "LED RED 0603", PartClass.DIODE, "led"),
        (None, "CAP CER 22UF 10V X7R 1210", PartClass.CAPACITOR, "ceramic"),
        (None, "Nch Small Signal MOSFET", PartClass.TRANSISTOR, "mosfet_n"),
    ],
)
def test_classify(
    refdes: str | None, desc: str | None, cls: PartClass, subtype: str | None
) -> None:
    c = classify(RawPart(refdes=refdes, description=desc))
    assert c.part_class is cls
    assert c.subtype == subtype
    assert c.confidence >= 0.7


def test_conflict_lowers_confidence_and_keeps_prefix() -> None:
    c = classify(RawPart(refdes="R3", description="CAP CER 1uF"))
    assert c.part_class is PartClass.RESISTOR and c.confidence < 0.7 and c.conflict


def test_unknown() -> None:
    c = classify(RawPart(refdes=None, description="mystery widget"))
    assert c.part_class is PartClass.UNKNOWN and c.confidence == 0.0


def test_topology_hints_are_collected_not_decisive() -> None:
    c = classify(RawPart(refdes="U1", description="Boost step-up converter"))
    assert c.part_class is PartClass.IC
    assert c.topology_hints == ("boost", "step-up")


def test_description_facts_mosfet() -> None:
    f = parse_description(
        "Single P-Channel 30 V 4.1 mOhm 125 nC OptiMOS Power Mosfet - TO-252-3-11",
        PartClass.TRANSISTOR,
    )
    assert f.ratings["v_ds"].value == 30
    assert f.ratings["rds_on"].value == pytest.approx(4.1e-3)
    assert f.ratings["qg"].value == pytest.approx(125e-9)
    assert f.package == "TO-252-3-11"


def test_seed_ratings_package_specific_overrides_star() -> None:
    r = seed_ratings(PartClass.RESISTOR, "0603")
    assert r["p_rated"].value == pytest.approx(0.1)
    assert r["t_knee"].value == 70 and r["t_max"].value == 155
    assert all(x.provenance is RatingProvenance.SEED for x in r.values())
    assert "verify" in r["p_rated"].provenance_ref
    assert "p_rated" not in seed_ratings(PartClass.RESISTOR, "9999")
    assert seed_ratings(PartClass.OTHER, None) == {}


def test_merge_ratings_later_wins() -> None:
    a = {"v": Rating(name="v", value=1, unit="V", provenance=RatingProvenance.SEED)}
    b = {"v": Rating(name="v", value=2, unit="V", provenance=RatingProvenance.USER)}
    assert merge_ratings(a, b)["v"].value == 2
    assert merge_ratings(b, a)["v"].value == 1


def test_catalog_overrides_description(session: Session, clock: FixedClock) -> None:
    repo = CatalogRepo(session, clock)
    repo.upsert(
        mpn="GCM32ER71A226KE12L",
        part_class=PartClass.CAPACITOR,
        ratings={
            "v_rated": Rating(
                name="v_rated",
                value=6.3,
                unit="V",
                provenance=RatingProvenance.USER,
                provenance_ref="datasheet p.2",
            )
        },
        pinmap={"1": "a", "2": "b"},
    )
    row = repo.find(mpn="GCM32ER71A226KE12L")
    assert row is not None and repo.pinmap_for(row) == {"1": "a", "2": "b"}
    # upsert again replaces, does not duplicate
    repo.upsert(mpn="GCM32ER71A226KE12L", part_class=PartClass.CAPACITOR, subtype="ceramic")
    assert repo.find(mpn="GCM32ER71A226KE12L").subtype == "ceramic"

    text = (
        "|RECORD=CatalogItem|DESCRIPTION=CAP CER 22UF 10V X7R 1210"
        "|USERCOMMENTS=GCM32ER71A226KE12L\r\n"
    )
    cb = classify_bom(read_bom(text.encode("latin-1"), "t.BomDoc"), session=session, clock=clock)
    v = cb.templates_by_mpn["GCM32ER71A226KE12L"].ratings.get("v_rated")
    assert v.value == 6.3 and v.provenance is RatingProvenance.USER


def test_find_by_libref_and_footprint(session: Session, clock: FixedClock) -> None:
    repo = CatalogRepo(session, clock)
    repo.upsert(
        mpn=None, libref="NMOS_GENERIC", footprint="SOT-23", part_class=PartClass.TRANSISTOR
    )
    assert repo.find(mpn=None, libref="NMOS_GENERIC", footprint="SOT-23") is not None
    assert repo.find(mpn=None, libref="NMOS_GENERIC", footprint="TO-220") is None
    assert repo.find(mpn="nope") is None


def test_duplicate_refdes_rows_are_errors() -> None:
    imported = BomImportResult(
        raw_parts=[
            RawPart(refdes="C1", value="10uF", source_row=1),
            RawPart(refdes="C1", value="22uF", source_row=2),
            RawPart(refdes="R1", value="junk!", source_row=3),
            RawPart(refdes=None, mpn=None, description="nothing", source_row=4),
        ],
        source_format="test",
        source_hash="x",
    )
    cb = classify_bom(imported)
    codes = sorted(d.code for d in cb.diagnostics)
    assert (
        "BOM_DUPLICATE_REFDES" in codes and "BOM_VALUE_UNPARSED" in codes and "BOM_NO_KEY" in codes
    )
    assert [p.refdes for p in cb.parts] == ["C1", "R1"]
    assert cb.parts[0].value_si == pytest.approx(10e-6)
    assert cb.parts[1].value_si is None
