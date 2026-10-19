from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from dfr.core.contracts import PartClass, RatingProvenance
from dfr.core.ports import FixedClock
from dfr.modules.m1_bom.catalog import CatalogRepo
from dfr.modules.m1_bom.catalog_io import (
    delete_dataset,
    export_catalog,
    import_catalog,
    list_datasets,
    parse_catalog,
)
from dfr.modules.m1_bom.pins import resolve_pin_functions
from dfr.modules.m1_bom.service import import_bom
from tests.conftest import FIXTURES

EXAMPLE = Path(__file__).resolve().parents[2] / "data" / "catalog" / "example_catalog.json"
CSV = """mpn,libref,footprint,class,subtype,rating,value,unit,source,pin,function
SPM6530T-100M-HZ,,,inductor,power,i_sat,5.2,A,TDK datasheet p.3 (test),,
SPM6530T-100M-HZ,,,inductor,power,i_rated,4.2,A,TDK datasheet p.3 (test),,
IPD90P03P4L-04,,,transistor,mosfet_p,v_ds,30,V,Infineon DS (test),,
IPD90P03P4L-04,,,transistor,mosfet_p,,,,,1,gate
IPD90P03P4L-04,,,transistor,mosfet_p,,,,,2,drain
IPD90P03P4L-04,,,transistor,mosfet_p,,,,,3,source
"""


def test_parse_example_json_validates() -> None:
    parsed = parse_catalog(EXAMPLE.read_bytes(), EXAMPLE.name)
    assert parsed.ok and parsed.fmt == "json" and parsed.dataset == "example"
    assert parsed.verify is True
    by = {e.key: e for e in parsed.entries}
    assert by["SPM6530T-100M-HZ"].ratings["dcr"].unit == "mohm"
    assert by["SPM6530T-100M-HZ"].ratings["dcr"].provenance is RatingProvenance.CATALOG
    assert "(verify)" in (by["SPM6530T-100M-HZ"].ratings["dcr"].provenance_ref or "")
    assert by["LM63635CC3QDRRRQ1"].pinmap["7"] == "sw"
    sym = by["NMOS_GENERIC@SOT-23"]
    assert sym.mpn is None and sym.libref == "NMOS_GENERIC" and sym.footprint == "SOT-23"


def test_parse_json_schema_errors_abort() -> None:
    bad = {
        "dataset": "x",
        "parts": {
            "ABC": {"class": "capacitor", "ratings": {"v_rated": {"value": 50, "unit": "V"}}}
        },
    }
    parsed = parse_catalog(json.dumps(bad).encode(), "bad.json")
    assert not parsed.ok and parsed.entries == []
    assert any("source" in d.message for d in parsed.diagnostics)
    parsed2 = parse_catalog(b"{not json", "bad.json")
    assert (
        parsed2.diagnostics[0].code == "CATALOG_JSON_INVALID"
        and parsed2.diagnostics[0].line_no == 1
    )
    weird = {
        "dataset": "x",
        "parts": {
            "ABC": {
                "class": "capacitor",
                "ratings": {"v_rated": {"value": 1, "unit": "zorkmid", "source": "abc"}},
            }
        },
    }
    assert any(
        d.code == "CATALOG_UNIT"
        for d in parse_catalog(json.dumps(weird).encode(), "u.json").diagnostics
    )


def test_parse_csv() -> None:
    parsed = parse_catalog(CSV.encode(), "my_parts.csv")
    assert parsed.ok and parsed.fmt == "csv" and parsed.dataset == "my_parts"
    by = {e.key: e for e in parsed.entries}
    assert by["SPM6530T-100M-HZ"].ratings["i_sat"].value == 5.2
    assert by["IPD90P03P4L-04"].pinmap == {"1": "gate", "2": "drain", "3": "source"}
    assert by["IPD90P03P4L-04"].part_class is PartClass.TRANSISTOR
    bad = "mpn,class,rating,value,unit,source\nX,capacitor,v_rated,abc,V,ds\nY,weird,v_rated,1,V,ds\nZ,capacitor,v_rated,1,V,\n"
    p = parse_catalog(bad.encode(), "bad.csv")
    assert not p.ok and len([d for d in p.diagnostics if d.code == "CATALOG_CSV_ROW"]) == 3
    assert all(d.line_no in (2, 3, 4) for d in p.diagnostics)
    assert parse_catalog(b"foo,bar\n1,2\n", "h.csv").diagnostics[0].code == "CATALOG_CSV_HEADER"


def test_import_reimport_delete_export(session: Session, clock: FixedClock) -> None:
    parsed = parse_catalog(EXAMPLE.read_bytes(), EXAMPLE.name)
    s1 = import_catalog(session, clock, parsed, filename=EXAMPLE.name)
    assert (s1.entries, s1.ratings, s1.pins, s1.replaced) == (3, 4, 15, False)
    sets = list_datasets(session, clock)
    assert [d["dataset"] for d in sets] == ["example"] and sets[0]["entries"] == 3

    # re-import with an edited value replaces the dataset in place (no duplicates)
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    doc["parts"]["SPM6530T-100M-HZ"]["ratings"]["i_sat"]["value"] = 5.2
    del doc["parts"]["NMOS_GENERIC@SOT-23"]
    s2 = import_catalog(
        session, clock, parse_catalog(json.dumps(doc).encode(), "e.json"), filename="e.json"
    )
    assert s2.replaced and s2.entries == 2
    repo = CatalogRepo(session, clock)
    assert len(repo.all_rows("example")) == 2
    assert repo.ratings_for(repo.find(mpn="SPM6530T-100M-HZ"))["i_sat"].value == 5.2

    # CSV import into a second dataset; the UI's own rows stay in dataset 'user'
    import_catalog(
        session, clock, parse_catalog(CSV.encode(), "my_parts.csv"), filename="my_parts.csv"
    )
    repo.upsert(mpn="HAND", part_class=PartClass.DIODE, pinmap={"1": "anode", "2": "cathode"})
    names = {d["dataset"] for d in list_datasets(session, clock)}
    assert names == {"example", "my_parts", "user"}

    exported = json.loads(export_catalog(session, clock, dataset="my_parts"))
    assert set(exported["parts"]) == {"SPM6530T-100M-HZ", "IPD90P03P4L-04"}
    assert exported["parts"]["IPD90P03P4L-04"]["pinmap"]["1"] == "gate"
    # export is re-importable
    again = parse_catalog(json.dumps({**exported, "dataset": "roundtrip"}).encode(), "r.json")
    assert again.ok and len(again.entries) == 2

    # the inductor existed in 'example'; my_parts merged into it and took ownership
    l1 = repo.find(mpn="SPM6530T-100M-HZ")
    assert l1.dataset == "my_parts" and set(repo.ratings_for(l1)) == {"i_rated", "dcr", "i_sat"}
    assert repo.ratings_for(l1)["i_sat"].provenance_ref == "TDK datasheet p.3 (test)"  # CSV won
    assert delete_dataset(session, clock, "my_parts") == 2
    assert {d["dataset"] for d in list_datasets(session, clock)} == {"example", "user"}
    assert repo.find(mpn="HAND") is not None  # user rows untouched
    assert len(repo.all_rows("example")) == 1  # U3 remains; L1 left with my_parts

    # invalid file imports nothing and does not disturb existing sets
    bad = import_catalog(session, clock, parse_catalog(b"{bad", "bad.json"), filename="bad.json")
    assert bad.entries == 0 and len(repo.all_rows("example")) == 1


def test_catalog_feeds_bom_import_and_pinouts(session: Session, clock: FixedClock) -> None:
    import_catalog(
        session, clock, parse_catalog(EXAMPLE.read_bytes(), EXAMPLE.name), filename=EXAMPLE.name
    )
    _, bom = import_bom(
        (FIXTURES / "design_c" / "design_c.BomDoc").read_bytes(),
        "d.BomDoc",
        session=session,
        clock=clock,
    )
    l1 = bom.templates_by_mpn["SPM6530T-100M-HZ"]
    assert (
        l1.ratings.get("i_sat").provenance is RatingProvenance.CATALOG
    )  # catalog beats description/seed
    assert l1.ratings.get("dcr").provenance is RatingProvenance.CATALOG
    assert (
        l1.ratings.get("t_max").provenance is RatingProvenance.SEED
    )  # not in catalog -> seed stays

    from dfr.modules.m1_bom.join import join_netlist
    from dfr.modules.m1_bom.netlist.service import import_netlist

    graph = import_netlist(
        (FIXTURES / "design_c" / "design_c_protel.net").read_bytes(), "d.net"
    ).graph
    parts = join_netlist(graph, bom).parts
    res = resolve_pin_functions(graph, parts, session=session, clock=clock)
    assert "U3" not in res.unresolved_refdes  # pinmap came from the catalog
    assert {p.pin_id: p.function for p in res.pins if p.refdes == "U3"}["7"] == "sw"
    assert "Q1" in res.unresolved_refdes


def test_missing_data_report(session: Session, clock: FixedClock, design_version_id: int) -> None:
    from dfr.app.catalog_report import format_missing, missing_data
    from dfr.core.db.repos import PartRepo
    from dfr.core.registry import discover
    from tests.conftest import make_part

    reg = discover(entry_points=False)
    PartRepo(session).add_many(
        design_version_id,
        [
            make_part(
                "L1", PartClass.INDUCTOR, mpn="SPM6530T-100M-HZ", ratings={"i_rated": (4.2, "A")}
            ),
            make_part(
                "Q1",
                PartClass.TRANSISTOR,
                mpn="IPD90P03P4L-04",
                subtype="mosfet_p",
                ratings={"v_ds": (30, "V"), "i_d": (90, "A"), "tj_max": (150, "degC")},
            ),
            make_part("J1", PartClass.CONNECTOR, mpn="X"),
            make_part(
                "C9",
                PartClass.CAPACITOR,
                subtype="ceramic",
                mpn="CAPX",
                ratings={"v_rated": (10, "V")},
            ),
        ],
    )
    rows = {r.refdes: r for r in missing_data(session, reg, design_version_id)}
    assert rows["L1"].missing_ratings == ["i_sat"] and not rows["L1"].in_catalog
    assert rows["Q1"].missing_ratings == [] and rows["Q1"].needs_pinout
    assert "J1" not in rows and "C9" not in rows  # connector ignored; capacitor complete
    text = format_missing(list(rows.values()))
    assert "i_sat" in text and "pinout" in text
    assert "every stressed part" in format_missing([])
