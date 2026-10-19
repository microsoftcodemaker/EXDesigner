from __future__ import annotations

import pytest

from dfr.core.contracts import PartClass, RatingProvenance, Severity
from dfr.modules.m1_bom.readers import default_readers, pick_reader
from dfr.modules.m1_bom.readers.bomdoc import BomDocReader, parse_record
from dfr.modules.m1_bom.service import import_bom, read_bom
from tests.conftest import FIXTURES

BOMDOC = FIXTURES / "design_c" / "design_c.BomDoc"


@pytest.fixture(scope="module")
def bomdoc_bytes() -> bytes:
    return BOMDOC.read_bytes()


def test_parse_record_handles_equals_in_values() -> None:
    rec = parse_record("|RECORD=X|A=1|URL=https://x/y?t=a=b|EMPTY=|")
    assert rec == {"RECORD": "X", "A": "1", "URL": "https://x/y?t=a=b", "EMPTY": ""}


def test_sniff_and_pick(bomdoc_bytes: bytes) -> None:
    assert BomDocReader().sniff(bomdoc_bytes, "whatever.txt")
    assert pick_reader(bomdoc_bytes, "x.txt", default_readers()).id == "altium_bomdoc"
    assert pick_reader(b"garbage", "x.BomDoc", default_readers()).id == "altium_bomdoc"  # by ext
    assert pick_reader(b"garbage", "x.csv", default_readers()) is None


def test_read_bomdoc_yields_22_items_and_links(bomdoc_bytes: bytes) -> None:
    """BOM-11: the supplied sample yields 22 catalog items."""
    res = read_bom(bomdoc_bytes, "design_c.BomDoc")
    assert res.source_format == "altium_bomdoc"
    assert not res.has_designators
    assert len(res.raw_parts) == 22
    assert all(p.refdes is None and p.mpn for p in res.raw_parts)
    assert len(res.source_hash) == 64
    assert "UMK212B7224KGHT" in res.links
    assert all(u.startswith("https://") for urls in res.links.values() for u in urls)
    assert not [d for d in res.diagnostics if d.severity is Severity.ERROR]


def test_classified_bomdoc_values_for_every_passive(bomdoc_bytes: bytes) -> None:
    _, cb = import_bom(bomdoc_bytes, "design_c.BomDoc")
    assert len(cb.templates_by_mpn) == 22
    assert cb.parts == []
    passives = [
        p
        for p in cb.templates_by_mpn.values()
        if p.part_class in (PartClass.CAPACITOR, PartClass.INDUCTOR, PartClass.RESISTOR)
    ]
    assert len(passives) == 12
    assert all(p.value_si is not None for p in passives), [
        p.mpn for p in passives if p.value_si is None
    ]

    l1 = cb.templates_by_mpn["SPM6530T-100M-HZ"]
    assert l1.part_class is PartClass.INDUCTOR
    assert l1.value_si == pytest.approx(10e-6) and l1.value_unit == "H"
    assert l1.ratings.get("i_rated").value == pytest.approx(4.2)
    assert l1.ratings.get("dcr").value == pytest.approx(0.08635)
    assert l1.ratings.get("dcr").provenance is RatingProvenance.BOM_DESCRIPTION

    c5 = cb.templates_by_mpn["GCM32ER71A226KE12L"]
    assert c5.value_si == pytest.approx(22e-6)
    assert c5.ratings.get("v_rated").value == 10
    assert c5.attributes["dielectric"] == "X7R"
    assert c5.package == "1210"
    assert c5.ratings.get("t_max").provenance is RatingProvenance.SEED

    r3 = cb.templates_by_mpn["CSM2512FT15L0"]
    assert r3.subtype == "sense" and r3.value_si == pytest.approx(0.015)
    assert r3.ratings.get("p_rated").provenance is RatingProvenance.SEED  # 2512 seed 1 W
    assert r3.ratings.get("p_rated").value == 1.0

    r7 = cb.templates_by_mpn["CRCW060388K7FKEA"]
    assert r7.value_si == pytest.approx(88.7e3)
    assert r7.ratings.get("p_rated").value == pytest.approx(0.1)
    assert r7.ratings.get("p_rated").provenance is RatingProvenance.BOM_DESCRIPTION

    u3 = cb.templates_by_mpn["LM63635CC3QDRRRQ1"]
    assert u3.part_class is PartClass.IC and u3.subtype == "switching_regulator"
    assert u3.ratings.get("v_out").value == pytest.approx(3.3)
    assert u3.ratings.get("i_out").value == pytest.approx(3.25)
    assert cb.topology_hints["LM63635CC3QDRRRQ1"] == ("buck",)

    q1 = cb.templates_by_mpn["IPD90P03P4L-04"]
    assert q1.subtype == "mosfet_p" and q1.attributes["channel"] == "p"
    assert q1.ratings.get("v_ds").value == 30
    assert q1.ratings.get("rds_on").value == pytest.approx(4.1e-3)
    assert q1.ratings.get("qg").value == pytest.approx(125e-9)

    assert cb.review_queue == []


def test_unknown_format_is_diagnostic_not_exception() -> None:
    res = read_bom(b"nope", "x.weird")
    assert res.raw_parts == []
    assert res.diagnostics[0].code == "BOM_UNKNOWN_FORMAT"


def test_duplicate_mpn_and_empty_item_reported() -> None:
    text = (
        "|RECORD=BOM|VERSION=6|KIND=ALTIUM_DESIGNER_LIVEBOM\r\n"
        "|RECORD=CatalogItem|DESCRIPTION=CAP CER 1UF 16V X7R 0805|USERCOMMENTS=ABC\r\n"
        "|RECORD=CatalogItem|DESCRIPTION=CAP CER 1UF 16V X7R 0805|USERCOMMENTS=ABC\r\n"
        "|RECORD=CatalogItem|DESCRIPTION=|USERCOMMENTS=\r\n"
        "junk line\r\n"
    )
    res = read_bom(text.encode("latin-1"), "t.BomDoc")
    codes = sorted(d.code for d in res.diagnostics)
    assert codes == ["BOMDOC_DUPLICATE_MPN", "BOMDOC_EMPTY_ITEM", "BOMDOC_UNPARSED_LINE"]
    assert all(d.line_no for d in res.diagnostics)
