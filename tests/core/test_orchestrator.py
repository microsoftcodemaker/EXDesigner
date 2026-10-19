from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from dfr.api import API_VERSION, DiagnosticSink, ModuleSpec, RunContext, StepResult
from dfr.app import Orchestrator, summarize
from dfr.core.contracts import Part, RunConfig, RunStatus, Severity, Source, Stat, StressValue, Tier
from dfr.core.db.repos import DiagnosticRepo, RunRepo, StressRepo
from dfr.core.ports import FixedClock
from tests.conftest import T0


def step_spec(mid: str, fn, requires=(), provides=(), optional=True) -> ModuleSpec:
    return ModuleSpec(
        id=mid,
        name=mid,
        version="1.0.0",
        api_version=API_VERSION,
        requires=tuple(requires),
        provides=tuple(provides),
        optional=optional,
        step=fn,
    )


def counting_step(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink("count")
    sink.info("COUNTED", f"{len(ctx.get('parts'))} parts")
    return StepResult.from_sink(sink, part_count=len(ctx.get("parts")))


def crashing_step(ctx: RunContext) -> StepResult:
    raise RuntimeError("kaboom")


def lazy_step(ctx: RunContext) -> StepResult:
    return StepResult()  # promised 'thing' but provides nothing


def test_run_analysis_sequences_steps_and_persists(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    specs = [
        step_spec("count", counting_step, requires=("parts",), provides=("part_count",)),
        step_spec(
            "downstream",
            lambda ctx: StepResult(outputs={"double": ctx.get("part_count") * 2}),
            requires=("part_count",),
            provides=("double",),
        ),
        step_spec("orphan", counting_step, requires=("no_such_cap",), provides=("x",)),
    ]
    orch = Orchestrator(session, specs, clock=clock)
    out = orch.run_analysis(design_version_id, RunConfig())

    assert out.ok and out.run.status is RunStatus.COMPLETED
    assert out.pipeline.ids == ["count", "downstream"]
    assert out.context.get("part_count") == 4  # DNP part excluded
    assert out.context.get("double") == 8
    assert out.run.model_set == {"count": "1.0.0", "downstream": "1.0.0"}

    stored = DiagnosticRepo(session).for_run(out.run.id)
    codes = {d.code for d in stored}
    assert {"PIPELINE_MISSING_DEP", "COUNTED"} <= codes
    assert RunRepo(session, clock).get(out.run.id).finished_at == T0
    assert summarize(stored)["info"] >= 1


def test_crashing_optional_step_does_not_fail_run(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    orch = Orchestrator(
        session,
        [
            step_spec("bad", crashing_step, provides=("bad",)),
            step_spec("good", counting_step, requires=("parts",), provides=("part_count",)),
        ],
        clock=clock,
    )
    out = orch.run_analysis(design_version_id, RunConfig())
    assert out.ok
    crash = [d for d in out.diagnostics if d.code == "STEP_CRASHED"]
    assert crash and crash[0].severity is Severity.ERROR and "kaboom" in crash[0].message
    assert out.context.get("part_count") == 4


def test_crashing_required_step_fails_run(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    orch = Orchestrator(session, [step_spec("bad", crashing_step, optional=False)], clock=clock)
    out = orch.run_analysis(design_version_id, RunConfig())
    assert out.run.status is RunStatus.FAILED


def test_incomplete_step_reported(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    orch = Orchestrator(session, [step_spec("lazy", lazy_step, provides=("thing",))], clock=clock)
    out = orch.run_analysis(design_version_id, RunConfig())
    assert any(d.code == "STEP_INCOMPLETE" for d in out.diagnostics)


def test_effective_stress_snapshot_and_rerun_chain(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    stress = StressRepo(session, clock)
    c5 = parts[0].id
    t1 = stress.add(
        StressValue(
            part_id=c5,
            param="i_rms",
            value=1.0,
            unit="A",
            stat=Stat.RMS,
            scenario="vin_max",
            source=Source.EQUATION,
            tier=Tier.T1,
            tool="t",
            tool_version="1",
            timestamp=T0,
        )
    )
    orch = Orchestrator(session, [], clock=clock)
    first = orch.run_analysis(design_version_id, RunConfig())
    assert first.context.get("effective_stress")[t1.key].value == 1.0

    t2 = stress.add(
        StressValue(
            part_id=c5,
            param="i_rms",
            value=1.4,
            unit="A",
            stat=Stat.RMS,
            scenario="vin_max",
            source=Source.MEASURED,
            tier=Tier.T2,
            tool="csv:scope.csv",
            tool_version="sha",
            timestamp=T0 + timedelta(minutes=1),
        )
    )
    second = orch.run_analysis(
        design_version_id, RunConfig(), parent_run_id=first.run.id, tier_level=Tier.T2
    )
    assert second.context.get("effective_stress")[t1.key].value == 1.4
    runs = RunRepo(session, clock)
    assert runs.effective_ids(first.run.id)[t1.key] == t1.id  # Tier 1 snapshot untouched
    assert runs.effective_ids(second.run.id)[t1.key] == t2.id
    assert [r.id for r in runs.chain(second.run.id)] == [first.run.id, second.run.id]


def test_unpersisted_override_is_used_but_flagged(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    override = StressValue(
        part_id=parts[0].id,
        param="v_peak",
        value=30.0,
        unit="V",
        stat=Stat.PEAK,
        source=Source.MANUAL,
        tier=Tier.T1,
        tool="prompt:user",
        tool_version="-",
        timestamp=T0,
        pinned=True,
    )
    out = Orchestrator(session, [], clock=clock).run_analysis(
        design_version_id, RunConfig(), overrides=[override]
    )
    assert out.context.get("effective_stress")[override.key].value == 30.0
    assert any(d.code == "RUN_UNPERSISTED_OVERRIDES" for d in out.diagnostics)


def test_example_module_runs_if_present(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock, specs
) -> None:
    out = Orchestrator(session, specs, clock=clock).run_analysis(design_version_id, RunConfig())
    assert out.ok
    if any(s.id == "example" for s in specs):
        assert out.context.get("example_marker") == "example@0.1.0"
