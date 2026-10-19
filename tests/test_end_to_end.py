"""Design C through the registry-driven workflow: import -> match -> confirm -> Tier 1 run."""

from __future__ import annotations

import pytest
from sqlalchemy import select

pytest.importorskip("dfr.topologies.buck", reason="end-to-end tests need the buck topology")
from sqlalchemy.orm import Session

from dfr.__main__ import main
from dfr.app import AnalysisInputs, run_tier1
from dfr.app.workflow import import_design, match_and_confirm
from dfr.core.contracts import ConverterSpec, DeratingStatus, RunStatus, Source, Tier
from dfr.core.db.models import DiagnosticRow
from dfr.core.db.repos import PartRepo, RunRepo, StressRepo
from dfr.core.ports import FixedClock
from dfr.core.registry import discover
from tests.conftest import FIXTURES

BOM = FIXTURES / "design_c" / "design_c.BomDoc"
NET = FIXTURES / "design_c" / "design_c_protel.net"
# Design C operating point from the board owner (PRD 8.2): 7-22 V in, 3.3 V / 3.25 A out,
# 400 kHz, 20 degC ambient.
SPEC = ConverterSpec(vin_min=7, vin_max=22, vout=3.3, iout_max=3.25, fsw=400e3, t_ambient=20)


@pytest.fixture
def registry():
    return discover(entry_points=False)


def test_design_c_tier1_end_to_end(session: Session, clock: FixedClock, registry) -> None:
    imported = import_design(
        session,
        registry,
        clock,
        name="Design C",
        bom_path=BOM,
        netlist_path=NET,
        topology="buck_integrated",
    )
    assert imported.part_count == 28 and imported.net_count == 19
    assert sorted(q.refdes for q in imported.pinout_requests) == [
        "D1",
        "D2",
        "D3",
        "Q1",
        "Q2",
        "U1",
        "U2",
        "U3",
    ]

    # Without confirmation nothing is persisted and Tier 1 refuses to run (REC-06).
    stage, _ = match_and_confirm(session, registry, clock, imported, topology="buck_integrated")
    assert stage is None
    refused = run_tier1(
        session, registry, AnalysisInputs(imported.design_version_id, SPEC), clock=clock
    )
    assert any(d.code == "APP_NO_CONFIRMED_STAGE" for d in refused.diagnostics)
    assert "m2_conditions" in refused.pipeline.skipped  # requires role_map/stage -> dropped
    assert any(d.code == "PIPELINE_MISSING_DEP" for d in refused.diagnostics)
    assert refused.context.get_or("stress", []) == []

    stage, _ = match_and_confirm(
        session, registry, clock, imported, topology="buck_integrated", auto_confirm=True
    )
    assert stage is not None and stage.id is not None
    out = run_tier1(
        session, registry, AnalysisInputs(imported.design_version_id, SPEC), clock=clock
    )
    assert out.ok and out.run.status is RunStatus.COMPLETED
    ids = out.pipeline.ids
    assert ids.index("m2_conditions") < ids.index("m5_derating")
    if "m6_thermal" in ids:
        assert ids.index("m6_thermal") < ids.index("m5_derating")

    parts = {p.refdes: p for p in PartRepo(session).for_version(imported.design_version_id)}
    inferred = out.context.get("inferred_values").values
    assert inferred["L"].value == pytest.approx(10e-6) and inferred["cout"].value == pytest.approx(
        44e-6
    )
    assert inferred["dcr"].value == pytest.approx(0.08635)

    stress = out.context.get("stress")
    assert all(s.id is not None for s in stress)  # persisted by M2's hook
    assert len(StressRepo(session, clock).for_version(imported.design_version_id)) == len(stress)
    l1 = [s for s in stress if s.part_id == parts["L1"].id and s.scenario == "vin_max"]
    assert {s.param for s in l1} == {"i_peak", "i_rms", "i_ripple_pp", "p_loss"}
    u3 = {s.param for s in stress if s.part_id == parts["U3"].id}
    assert u3 == {
        "i_rms_hs",
        "i_rms_ls",
        "i_peak",
        "v_peak",
        "i_out",
    }  # no p_loss: prompted instead
    prompts = out.context.get("prompts")
    assert len(prompts) == 1 and prompts[0].id is not None and prompts[0].part_id == parts["U3"].id
    assert (
        StressRepo(session, clock).open_prompts(imported.design_version_id)[0].id == prompts[0].id
    )

    derating = {
        (parts_by_id := {p.id: p for p in parts.values()})[r.part_id].refdes + ":" + r.rule_id: r
        for r in out.context.get("derating")
    }
    # 22 V on a 35 V X7R: over the 0.5 x limit (17.5 V) but under the rating -> WARN
    assert derating["C2:cap_ceramic_voltage"].status is DeratingStatus.WARN
    assert derating["C2:cap_ceramic_voltage"].margin == pytest.approx(-0.257, abs=1e-3)
    # 22 V on a 50 V X7R: limit 25 V -> PASS with 12 % margin
    assert derating["C1:cap_ceramic_voltage"].status is DeratingStatus.PASS
    assert derating["C1:cap_ceramic_voltage"].margin == pytest.approx(0.12, abs=1e-3)
    assert derating["C5:cap_ceramic_voltage"].status is DeratingStatus.PASS
    assert derating["L1:ind_isat"].status is DeratingStatus.UNKNOWN  # no Isat rating -> never PASS
    assert derating["L1:ind_irms"].status is DeratingStatus.PASS
    assert derating["U3:ic_iout"].status is DeratingStatus.WARN  # 3.25 A on a 3.25 A part
    assert all(r.stress_value_ids for r in out.context.get("derating") if r.rule_id != "ic_tj")
    del parts_by_id

    # Thermal: nothing without theta ratings, said out loud (when the module is installed).
    if "m6_thermal" in ids:
        assert out.context.get("thermal") == []
        assert any(d.code == "THERMAL_NO_THETA" for d in out.diagnostics)

    # Run row is frozen with its snapshot and diagnostics persisted.
    runs = RunRepo(session, clock)
    stored = runs.get(out.run.id)
    assert stored.finished_at is not None and stored.model_set["m2_conditions"]
    assert len(runs.effective_ids(out.run.id)) == len(stress)
    assert session.scalars(select(DiagnosticRow).where(DiagnosticRow.run_id == out.run.id)).all()
    assert len(session.execute(select(DiagnosticRow)).all()) >= len(out.diagnostics) - 2

    # Tier 2 re-run with a measured override on C2 chains to the first run.
    repo = StressRepo(session, clock)
    stored_c2 = next(
        s
        for s in stress
        if s.part_id == parts["C2"].id and s.param == "v_dc" and s.scenario == "vin_max"
    )
    assert stored_c2.value == 22.0
    clock.advance(minutes=1)
    repo.add(
        stored_c2.model_copy(
            update={
                "id": None,
                "value": 16.0,
                "tier": Tier.T2,
                "source": Source.MEASURED,
                "tool": "scope",
                "timestamp": clock.now(),
            }
        )
    )
    second = run_tier1(
        session,
        registry,
        AnalysisInputs(imported.design_version_id, SPEC),
        clock=clock,
        parent_run_id=out.run.id,
        tier_level=Tier.T2,
    )
    assert second.ok and [r.id for r in runs.chain(second.run.id)] == [out.run.id, second.run.id]
    c2_again = next(
        r
        for r in second.context.get("derating")
        if r.part_id == parts["C2"].id and r.rule_id == "cap_ceramic_voltage"
    )
    assert (
        c2_again.stress == 16.0 and c2_again.status is DeratingStatus.PASS
    )  # measured T2 (16 V) beat the equation T1 (22 V) and clears the 17.5 V limit


def test_cli_analyze_design_c(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "analyze",
            "--bom",
            str(BOM),
            "--netlist",
            str(NET),
            "--topology",
            "buck_integrated",
            "--vin-min",
            "7",
            "--vin-max",
            "22",
            "--vout",
            "3.3",
            "--iout",
            "3.25",
            "--fsw",
            "400e3",
            "--ta",
            "20",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Stage buck_integrated" in out and "rail sw    = NetC3_1" in out
    assert "WARN" in out and "cap_ceramic_voltage" in out and "PROMPT U3 p_loss" in out


def test_cli_analyze_no_match_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "analyze",
            "--bom",
            str(BOM),
            "--netlist",
            str(NET),
            "--topology",
            "buck",
            "--vin-min",
            "7",
            "--vin-max",
            "22",
            "--vout",
            "3.3",
            "--iout",
            "3.25",
            "--fsw",
            "400e3",
        ]
    )
    assert rc == 1 and "No stage matched" in capsys.readouterr().out
