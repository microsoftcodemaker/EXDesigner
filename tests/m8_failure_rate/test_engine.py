"""Parts-stress engine (MTB-01/04): hand-calculated pi factors, forms, exclusions, series roll-up."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dfr.core.contracts import (
    Part,
    PartClass,
    Rating,
    RatingProvenance,
    RatingSet,
    Source,
    Stat,
    StressValue,
    ThermalResult,
    Tier,
)
from dfr.modules.m8_failure_rate.engine import arrhenius, interpolate, parts_stress
from dfr.modules.m8_failure_rate.tables import load_table_file, load_tables

HERE = Path(__file__).parent
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def part(pid, refdes, cls=PartClass.CAPACITOR, subtype=None, value_si=None, **ratings) -> Part:
    return Part(
        id=pid,
        refdes=refdes,
        part_class=cls,
        subtype=subtype,
        value_si=value_si,
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit="", provenance=RatingProvenance.CATALOG)
                for k, v in ratings.items()
            }
        ),
    )


def sv(sid, pid, param, value) -> StressValue:
    return StressValue(
        id=sid,
        part_id=pid,
        param=param,
        value=value,
        unit="V",
        stat=Stat.DC,
        scenario="vin_max",
        source=Source.EQUATION,
        tier=Tier.T1,
        tool="t",
        tool_version="1",
        timestamp=NOW,
    )


@pytest.fixture(scope="module")
def table():
    t = load_table_file(HERE / "dummy_parts_stress.yaml")
    assert t.version == 1 and not t.diagnostics
    return t


def test_arrhenius_hand_values() -> None:
    kb = 8.617e-5
    assert arrhenius(25.0, 0.35, kb) == pytest.approx(1.0)
    assert arrhenius(75.0, 0.35, kb) == pytest.approx(7.0746, rel=1e-3)
    assert arrhenius(125.0, 0.7, kb) == pytest.approx(937.50, rel=1e-3)


def test_interpolate_linear_log_and_clamps() -> None:
    c = [(0.0, 1.0), (0.5, 1.0), (1.0, 2.0)]
    assert interpolate(c, 0.75) == pytest.approx(1.5)
    assert interpolate(c, 2.0) == 2.0 and interpolate(c, -1.0) == 1.0
    assert interpolate([(1e-9, 1.0), (1e-3, 10.0)], 1e-6, log=True) == pytest.approx(5.5)


def test_product_form_series_and_exclusions(table) -> None:
    parts = [
        part(1, "C1", v_rated=10.0),  # ratio 0.75 -> piV 1.5; Tj 75 -> piT 7.0746
        part(2, "C2", subtype="ceramic", value_si=1e-6),  # piC 5.5, piQ 3
        part(3, "L1", PartClass.INDUCTOR),  # no 'commercial' row -> excluded
        part(4, "U1", PartClass.IC),  # requires_tj and no Tj -> excluded
        part(5, "R1", PartClass.RESISTOR),  # no entry -> excluded
        part(6, "C3"),  # no v_dc stress / v_rated -> excluded
    ]
    eff = {s.key: s for s in [sv(10, 1, "v_dc", 7.5)]}
    th = [ThermalResult(part_id=1, scenario="vin_max", tj=75.0)]
    r = parts_stress(parts, eff, table, th, t_ambient=25.0)
    by = {p.part_id: p for p in r.per_part}
    # C1: 0.02 * 7.0746 * 1.5 * 10 * 1 = 2.1224 /1e6 h = 2122.4 FIT
    assert by[1].lambda_fit == pytest.approx(2122.4, rel=1e-3)
    assert by[1].factors["piV"] == 1.5 and by[1].factors["t_c"] == 75.0
    # C2: 0.01 * 5.5 * 3 = 0.165 /1e6 h = 165 FIT
    assert by[2].lambda_fit == pytest.approx(165.0, rel=1e-3)
    assert r.system_lambda_fit == pytest.approx(2287.4, rel=1e-3)
    assert r.system_mtbf_h == pytest.approx(1e9 / 2287.4, rel=1e-3)
    assert r.excluded_part_ids == [3, 4, 5, 6]
    assert "piQ: no table row for quality = commercial" in r.excluded_reasons[3]
    assert "no junction temperature" in r.excluded_reasons[4]
    assert r.excluded_reasons[5] == "no table entry for resistor/-"
    assert "needs stress v_dc and rating v_rated" in r.excluded_reasons[6]
    assert r.per_part[0].part_id == 1 and r.table_id == "dummy_parts_stress"
    assert r.reliability_curve is not None and r.reliability_curve[0][1] == pytest.approx(
        1.0, abs=1e-4
    )
    assert r.reliability_curve[-1][1] == pytest.approx(math.exp(-3.0), rel=1e-3)  # 3 MTBF
    assert any("1 excluded" not in a and "4 excluded" in a for a in r.assumptions)


def test_ic_sum_form_quality_override_and_ta_fallback(table) -> None:
    u1 = part(4, "U1", PartClass.IC)
    c1 = part(1, "C1", v_rated=10.0).model_copy(update={"attributes": {"quality": "M"}})
    eff = {s.key: s for s in [sv(10, 1, "v_dc", 2.0)]}
    th = [
        ThermalResult(part_id=4, scenario="a", tj=125.0),
        ThermalResult(part_id=4, scenario="b", tj=100.0),
    ]
    r = parts_stress([u1, c1], eff, table, th, t_ambient=25.0, environment="GB")
    by = {p.part_id: p for p in r.per_part}
    # U1 (worst Tj 125): (0.01 * 937.50 + 0.005 * 1) * 2 * 1 = 18.76 /1e6 h
    assert by[4].lambda_fit == pytest.approx(18760.0, rel=1e-3)
    # C1 at Ta (no Tj): piT 1, piV 1 (ratio 0.2), piQ 1 (attribute M) -> 0.02 /1e6 h = 20 FIT
    assert by[1].lambda_fit == pytest.approx(20.0, rel=1e-3)
    assert any("no Tj for C1" in a for a in r.assumptions)


def test_empty_shipped_tables_exclude_everything() -> None:
    tables = load_tables()
    assert {"mil_hdbk_217f", "sr_332", "pof"} <= set(tables)
    t = tables["mil_hdbk_217f"]
    assert t.is_empty and t.rate_unit == "per_1e6_h" and not t.diagnostics
    r = parts_stress([part(1, "C1", v_rated=10.0)], {}, t)
    assert r.system_lambda_fit is None and r.excluded_part_ids == [1]
    assert any("import one" in a for a in r.assumptions)


def test_invalid_table_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad\nmethod: parts_stress\nversion: 1\nsource: s\nconfidence: low\n", encoding="utf-8"
    )
    t = load_table_file(bad)
    assert t.version == 0 and any("rate_unit" in d.message for d in t.diagnostics)
    bad.write_text("id: [unclosed\n", encoding="utf-8")
    assert "YAML error" in load_table_file(bad).diagnostics[0].message
