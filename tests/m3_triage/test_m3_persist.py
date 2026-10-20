"""M3 through the orchestrator: rows persisted, prompts stored once, waivers reach the step."""

from __future__ import annotations

import pytest

from dfr.core.contracts import (
    DeratingResult,
    DeratingStatus,
    PromptOrigin,
    RoleMap,
    RunConfig,
    Stage,
    StageStatus,
)
from dfr.core.db.repos import StressRepo
from dfr.core.registry import ModuleSpec
from dfr.core.registry.spec import RunContext, StepResult
from dfr.modules.m3_triage.module import MODULE, load_results, run_context, unwaive, waive


def _fake_derating() -> ModuleSpec:
    def step(ctx: RunContext) -> StepResult:
        parts = {p.refdes: p.id for p in ctx.get("parts")}
        rows = [
            DeratingResult(
                part_id=parts["C5"],
                param="v_dc",
                stress=9,
                limit=5,
                rating=10,
                ratio=1.8,
                status=DeratingStatus.WARN,
                margin=-0.8,
                rule_id="cap_ceramic_voltage",
            ),
            DeratingResult(
                part_id=parts["L1"],
                param="i_peak",
                stress=3.6,
                limit=None,
                rating=None,
                ratio=None,
                status=DeratingStatus.UNKNOWN,
                margin=None,
                rule_id="ind_isat",
            ),
        ]
        return StepResult(outputs={"derating": rows})

    return ModuleSpec(
        id="fake_derating",
        name="f",
        version="0",
        api_version=MODULE.api_version,
        requires=("parts",),
        provides=("derating",),
        step=step,
    )


@pytest.fixture
def stage() -> Stage:
    return Stage(
        pattern_id="buck_integrated",
        pattern_version="1",
        match_confidence=1.0,
        status=StageStatus.CONFIRMED,
    )


def _run(session, clock, design_version_id, stage, parent=None):
    from dfr.app.orchestrator import Orchestrator

    orch = Orchestrator(session, [_fake_derating(), MODULE], clock=clock)
    extra = {
        "stage": stage,
        "role_map": RoleMap(roles={"ic": ("U3",), "inductor": ("L1",), "output_cap": ("C5", "C6")}),
    }
    extra.update(run_context(session, design_version_id))
    return orch.run_analysis(
        design_version_id, RunConfig(), extra_context=extra, parent_run_id=parent
    )


def test_persist_load_prompts_and_waivers(session, clock, design_version_id, parts, stage) -> None:
    out = _run(session, clock, design_version_id, stage)
    assert out.ok and out.pipeline.ids == ["fake_derating", "m3_triage"]
    items = out.context.get("refinement")
    refdes = {p.id: p.refdes for p in parts}
    assert [refdes[i.part_id] for i in items] == ["L1", "C5", "U3"]
    assert all(i.id is not None for i in items)
    l1 = items[0]
    assert l1.flags == ["F0", "F4:inductor_isat_load_step"] and l1.prompts[0].id is not None
    stored = load_results(session, out.run.id)
    assert [(i.part_id, i.flags, i.score) for i in stored] == [
        (i.part_id, i.flags, i.score) for i in items
    ]
    assert stored[0].prompts == []  # prompts live in value_prompt, not in the item row
    open_prompts = StressRepo(session, clock).open_prompts(design_version_id)
    assert {(p.part_id, p.param, p.scenario) for p in open_prompts} == {
        (l1.part_id, "i_peak", "load_step"),
        (items[2].part_id, "v_peak", "vin_max"),
    }
    assert all(p.origin is PromptOrigin.M3 for p in open_prompts)

    # Re-run: open prompts are not requested again; a waiver turns C5's F1 into a waived item.
    c5 = items[1].part_id
    waive(session, clock, design_version_id, c5, "F1", "transient only")
    with pytest.raises(ValueError):
        waive(session, clock, design_version_id, c5, "F1", "  ")
    out2 = _run(session, clock, design_version_id, stage, parent=out.run.id)
    items2 = out2.context.get("refinement")
    assert sum(len(i.prompts) for i in items2) == 0
    assert len(StressRepo(session, clock).open_prompts(design_version_id)) == 2
    c5_item = next(i for i in items2 if i.part_id == c5)
    assert c5_item.status == "waived" and c5_item.waiver_reason == "transient only"
    assert [i.status for i in items2] == ["open", "open", "waived"]
    assert unwaive(session, design_version_id, c5, "F1") and not unwaive(
        session, design_version_id, c5, "F1"
    )
    assert run_context(session, design_version_id)["triage_context"]["waivers"] == []
