"""M8 through the orchestrator: method selection, persistence round-trip, report section."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from dfr.app.orchestrator import Orchestrator
from dfr.core.contracts import Confidence, LifetimeResult, MissionProfile, RunConfig
from dfr.core.registry import ModuleSpec
from dfr.core.registry.spec import RunContext, StepResult
from dfr.modules.m8_failure_rate.module import MODULE, bundle_extras, load_results
from dfr.modules.m8_failure_rate.report import SPEC, render_failure_rate, sections
from dfr.modules.m8_failure_rate.tables import load_table, load_table_file

HERE = Path(__file__).parent


def _fake_lifetime() -> ModuleSpec:
    def step(ctx: RunContext) -> StepResult:
        ids = {p.refdes: p.id for p in ctx.get("parts")}
        return StepResult(
            outputs={
                "lifetime": [
                    LifetimeResult(
                        part_id=ids["C5"],
                        mechanism="electrolyte_dry_out",
                        model_id="m",
                        life_hours=1e5,
                        confidence=Confidence.LOW,
                    ),
                    LifetimeResult(
                        part_id=ids["U3"],
                        mechanism="thermal_cycling_fatigue",
                        model_id="m",
                        life_hours=None,
                        confidence=Confidence.LOW,
                        assumptions=("not available: no Tj",),
                    ),
                ]
            }
        )

    return ModuleSpec(
        id="fake_lifetime",
        name="f",
        version="0",
        api_version=MODULE.api_version,
        requires=("parts",),
        provides=("lifetime",),
        step=step,
    )


@pytest.fixture
def tables():
    return {
        "dummy_parts_stress": load_table_file(HERE / "dummy_parts_stress.yaml"),
        "pof": load_table("pof"),
    }


@pytest.mark.usefixtures("parts")
def test_all_methods_persist_and_reload(session, clock, design_version_id, tables) -> None:
    orch = Orchestrator(session, [_fake_lifetime(), MODULE], clock=clock)
    out = orch.run_analysis(
        design_version_id,
        RunConfig(extra={"fr_environment": "GF"}),
        extra_context={"failure_rate_tables": tables, "mission_profile": MissionProfile()},
    )
    assert out.ok and out.pipeline.ids == ["fake_lifetime", "m8_failure_rate"]
    results = out.context.get("failure_rate")
    assert [r.method for r in results] == ["dummy_parts_stress", "pof"]
    ps, pof = results
    # C5/C6 have v_rated but no v_dc stress -> excluded; L1 no quality row; U3 no Tj: nothing rated
    assert ps.system_lambda_fit is None and len(ps.excluded_part_ids) == 4
    assert any("environment GF" in a for a in ps.assumptions)
    assert pof.system_mttf_h == pytest.approx(89297.95, rel=1e-3) and pof.system_mtbf_h is None
    stored = load_results(session, out.run.id)
    assert [r.model_dump() for r in stored] == [r.model_dump() for r in results]
    assert bundle_extras(session, out.run.id)["failure_rate"][1].b10_h == pytest.approx(
        47230.87, rel=1e-3
    )
    codes = {d.code for d in out.diagnostics}
    assert {"FAILURE_RATE_NOT_AVAILABLE", "FAILURE_RATE_SUMMARY"} <= codes


@pytest.mark.usefixtures("parts")
def test_method_selection(session, clock, design_version_id, tables) -> None:
    orch = Orchestrator(session, [MODULE], clock=clock)
    out = orch.run_analysis(
        design_version_id,
        RunConfig(failure_rate_method="pof"),
        extra_context={"failure_rate_tables": tables},
    )
    assert out.context.get("failure_rate") == []  # pof needs M7; nothing else selected
    assert any(d.code == "FAILURE_RATE_POF_SKIPPED" for d in out.diagnostics)
    out2 = orch.run_analysis(
        design_version_id,
        RunConfig(failure_rate_method="nope"),
        extra_context={"failure_rate_tables": tables},
    )
    assert any(d.code == "FAILURE_RATE_NO_TABLE" for d in out2.diagnostics)


@dataclass
class FakeBundle:
    extras: dict[str, Any] = field(default_factory=dict)

    def refdes(self, part_id: int) -> str:
        return f"P{part_id}"


def test_report_section(tables) -> None:
    from dfr.modules.m8_failure_rate.pof import weibull_rollup

    pof = weibull_rollup(
        [
            LifetimeResult(
                part_id=1,
                mechanism="wear_out",
                model_id="m",
                life_hours=1e5,
                confidence=Confidence.LOW,
            )
        ],
        tables["pof"],
    )
    html = render_failure_rate(FakeBundle({"failure_rate": [pof]}))
    values = re.findall(r'<span class="value">([^<]*)</span><span class="badge t1">', html)
    assert values[:2] == ["10.2 y", "5.4 y"]  # MTTF, B10 in years
    assert "Model comparison" in html and "MTBF not shown" in html
    assert "<p class='muted'>" in render_failure_rate(FakeBundle())
    assert MODULE.services["report.sections"] is sections and sections()[0][0] is SPEC
