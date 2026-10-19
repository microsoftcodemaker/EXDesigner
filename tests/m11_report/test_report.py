"""RPT-01/RPT-02: HTML report from stored runs; 100 % of displayed numbers carry badges."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from dfr.core.contracts import ConverterSpec, Source, Tier
from dfr.core.db.repos import StressRepo
from dfr.core.ports import FixedClock
from dfr.core.registry import discover
from dfr.modules.m11_report.module import build_report_html, load_bundle, write_report_html
from dfr.modules.m11_report.sections import num
from tests.conftest import FIXTURES

pytest.importorskip("dfr.topologies.buck")
BOM = FIXTURES / "design_c" / "design_c.BomDoc"
NET = FIXTURES / "design_c" / "design_c_protel.net"
SPEC = ConverterSpec(vin_min=8, vin_max=36, vout=3.3, iout_max=3.25, fsw=400e3, t_ambient=40)


@pytest.fixture
def two_runs(session: Session, clock: FixedClock):
    from dfr.app import AnalysisInputs, run_tier1
    from dfr.app.workflow import import_design, match_and_confirm

    reg = discover(entry_points=False)
    imp = import_design(
        session,
        reg,
        clock,
        name="Design C",
        bom_path=BOM,
        netlist_path=NET,
        topology="buck_integrated",
    )
    match_and_confirm(session, reg, clock, imp, topology="buck_integrated", auto_confirm=True)
    first = run_tier1(session, reg, AnalysisInputs(imp.design_version_id, SPEC), clock=clock)
    c2 = next(
        s
        for s in first.context.get("stress")
        if s.param == "v_dc" and s.scenario == "vin_max" and s.value == 36.0
    )
    clock.advance(minutes=1)
    StressRepo(session, clock).add(
        c2.model_copy(
            update={
                "id": None,
                "value": 30.0,
                "tier": Tier.T2,
                "source": Source.MEASURED,
                "tool": "csv:scope.csv",
                "timestamp": clock.now(),
            }
        )
    )
    second = run_tier1(
        session,
        reg,
        AnalysisInputs(imp.design_version_id, SPEC),
        clock=clock,
        parent_run_id=first.run.id,
        tier_level=Tier.T2,
    )
    return reg, first, second


def test_num_macro_always_badges() -> None:
    assert 'class="badge t1"' in num(1.0, 1, "equation") and ">eq<" in num(1.0, 1, "equation")
    assert ">—<" in num(None, 2, "measured") and "badge t2" in num(None, 2, "measured")


def test_report_html_every_number_has_tier_and_source(
    two_runs, session: Session, clock: FixedClock
) -> None:
    reg, first, second = two_runs
    html = build_report_html(session, reg, second.run.id, clock=clock)
    values = re.findall(
        r'<span class="value">([^<]*)</span><span class="badge t([12])"></span>|<span class="value">',
        html,
    )
    n_values = len(re.findall(r'<span class="value">', html))
    n_badged = len(
        re.findall(
            r'<span class="value">[^<]*</span><span class="badge t[12]">T[12]</span><span class="src">',
            html,
        )
    )
    assert n_values > 40 and n_badged == n_values, (
        "RPT-02: 100 % of displayed numbers carry badge + source"
    )
    assert "Design C" in html and "Executive summary" in html and "Ranked risk list" in html
    assert "FAIL" in html and "cap_ceramic_voltage" in html
    assert 'badge t2">T2' in html and ">meas<" in html  # the measured C2 value made it in
    assert f"refines run #{first.run.id}" in html and "Before" in html  # refinement section
    assert "not a safety certification" in html
    del values


def test_bundle_and_sections_filter(two_runs, session: Session, clock: FixedClock) -> None:
    reg, first, second = two_runs
    b = load_bundle(session, reg, second.run.id, clock)
    assert b.parent is not None and b.parent.run.id == first.run.id
    assert len(b.effective) == len(first.context.get("stress"))
    assert b.derating and b.refdes(b.derating[0].part_id)
    only = build_report_html(session, reg, first.run.id, clock=clock, section_ids=["summary"])
    assert "Executive summary" in only and "Per-part stress values" not in only
    assert "Single run; no refinement chain" in build_report_html(
        session, reg, first.run.id, clock=clock
    )


def test_write_report_file(two_runs, session: Session, clock: FixedClock, tmp_path: Path) -> None:
    reg, first, _ = two_runs
    out = write_report_html(session, reg, first.run.id, tmp_path / "sub" / "r.html", clock=clock)
    assert out.exists() and out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_unknown_run(session: Session, clock: FixedClock) -> None:
    with pytest.raises(LookupError):
        load_bundle(session, discover(entry_points=False), 999, clock)
