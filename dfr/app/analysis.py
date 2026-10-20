"""Application service: assemble the context for a Tier 1 run and execute it.

Gathers what the orchestrator cannot know by itself: the confirmed stage and its role map
(M12 tables), the converter spec (user form), topology templates (registry services), and
the derating rule set. Still imports no module package; everything comes through the
registry's service table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from dfr.app.orchestrator import Orchestrator, RunOutcome
from dfr.core.contracts import (
    ConverterSpec,
    MissionProfile,
    RunConfig,
    Stage,
    StageStatus,
    StressValue,
    Tier,
)
from dfr.core.db.repos import StageRepo
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.ports import Clock, SystemClock
from dfr.core.registry import DiscoveryResult


@dataclass(frozen=True)
class AnalysisInputs:
    design_version_id: int
    spec: ConverterSpec
    config: RunConfig = field(default_factory=RunConfig)
    stage_id: int | None = None  # default: the latest confirmed stage of the version
    inferred_overrides: dict[str, float] | None = None
    part_params: dict[str, float] | None = None
    profile: MissionProfile | None = None  # lifetime usage assumptions (M7); None = defaults


def run_tier1(
    session: Session,
    registry: DiscoveryResult,
    inputs: AnalysisInputs,
    *,
    clock: Clock | None = None,
    overrides: list[StressValue] | None = None,
    parent_run_id: int | None = None,
    tier_level: Tier = Tier.T1,
) -> RunOutcome:
    clock = clock or SystemClock()
    sink = DiagnosticSink("app")
    stages = StageRepo(session, clock)
    stage = _pick_stage(stages, inputs, sink)

    extra: dict[str, Any] = {"converter_spec": inputs.spec, "templates": _templates(registry)}
    if stage is not None and stage.id is not None:
        extra["stage"] = stage
        extra["role_map"] = stages.role_map(stage.id)
    if inputs.inferred_overrides:
        extra["inferred_overrides"] = inputs.inferred_overrides
    if inputs.part_params:
        extra["part_params"] = inputs.part_params
    if inputs.profile is not None:
        extra["mission_profile"] = inputs.profile
    if registry.has_service("load_ruleset"):
        extra["ruleset"] = registry.service("load_ruleset")(inputs.config.ruleset_id)
    # Modules that need stored per-version state at run time (waivers, open prompts, ...)
    # expose a ``run_context(session, design_version_id) -> Mapping`` service.
    for provider in registry.services_named("run_context"):
        extra.update(provider(session, inputs.design_version_id))
    config = inputs.config.with_inputs(inputs.spec, inputs.profile)

    orch = Orchestrator(session, registry.modules, clock=clock)
    outcome = orch.run_analysis(
        inputs.design_version_id,
        config,
        overrides=overrides,
        parent_run_id=parent_run_id,
        tier_level=tier_level,
        extra_context=extra,
    )
    outcome.diagnostics[:0] = list(sink.items)
    return outcome


def _pick_stage(stages: StageRepo, inputs: AnalysisInputs, sink: DiagnosticSink) -> Stage | None:
    if inputs.stage_id is not None:
        stage = stages.get(inputs.stage_id)
    else:
        confirmed = [
            s
            for s in stages.for_version(inputs.design_version_id)
            if s.status is StageStatus.CONFIRMED
        ]
        stage = confirmed[-1] if confirmed else None
    if stage is None:
        sink.error(
            "APP_NO_CONFIRMED_STAGE",
            "no confirmed stage for this design version; "
            "confirm roles on Circuit Review before running Tier 1",
        )
        return None
    if stage.status is not StageStatus.CONFIRMED:
        sink.error(
            "APP_STAGE_NOT_CONFIRMED", f"stage {stage.id} is {stage.status.value}; confirm it first"
        )
        return None
    return stage


def _templates(registry: DiscoveryResult) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for provider in registry.services_named("topology.templates"):
        out.update(provider())
    return out
