"""Orchestrator: sequences registry-built pipeline steps on an immutable run (PRD section 2.6).

It knows no module by name. Steps come from ``build_pipeline`` and exchange data only
through the capability bag (``RunContext``). Each run is persisted before any step runs
and frozen (``finish``) afterwards, with every diagnostic stored against it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from dfr.core.contracts.v1 import (
    AnalysisRun,
    Diagnostic,
    RunConfig,
    RunStatus,
    Severity,
    StressValue,
    Tier,
)
from dfr.core.db.repos import DiagnosticRepo, PartRepo, RunRepo, StressRepo
from dfr.core.db.repos.stress import resolve_effective_stress
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.ports import Clock, SystemClock
from dfr.core.registry import ModuleSpec, Pipeline, RunContext, build_pipeline

# Capabilities the orchestrator itself seeds before any module step runs.
SEED_CAPABILITIES = ("parts", "effective_stress", "run", "config")


@dataclass
class RunOutcome:
    run: AnalysisRun
    pipeline: Pipeline
    context: RunContext
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.run.status is RunStatus.COMPLETED


class Orchestrator:
    def __init__(
        self,
        session: Session,
        specs: Sequence[ModuleSpec],
        *,
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.specs = list(specs)
        self.clock = clock or SystemClock()
        self.runs = RunRepo(session, self.clock)
        self.diags = DiagnosticRepo(session)
        self.parts = PartRepo(session)
        self.stress = StressRepo(session, self.clock)

    def plan(self, cfg: RunConfig) -> Pipeline:
        return build_pipeline(
            self.specs, enabled=cfg.enabled_modules, initial_capabilities=SEED_CAPABILITIES
        )

    def run_analysis(
        self,
        design_version_id: int,
        cfg: RunConfig,
        *,
        overrides: Iterable[StressValue] | None = None,
        parent_run_id: int | None = None,
        tier_level: Tier = Tier.T1,
        extra_context: Mapping[str, Any] | None = None,
    ) -> RunOutcome:
        pipeline = self.plan(cfg)
        sink = DiagnosticSink("orchestrator")
        sink.extend(pipeline.diagnostics)

        run = self.runs.start(
            design_version_id,
            cfg,
            tier_level=tier_level,
            parent_run_id=parent_run_id,
            model_set={s.id: s.version for s in pipeline.steps},
        )
        assert run.id is not None

        parts = self.parts.for_version(design_version_id, include_dnp=False)
        stored = self.stress.for_version(design_version_id)
        effective = resolve_effective_stress([*stored, *(overrides or [])])
        persisted_effective = {k: v for k, v in effective.items() if v.id is not None}
        if len(persisted_effective) != len(effective):
            sink.warning(
                "RUN_UNPERSISTED_OVERRIDES",
                "some override stress values are not stored and were used but not snapshotted",
            )
        self.runs.snapshot_effective(run.id, persisted_effective)

        ctx = RunContext(
            {
                "parts": parts,
                "effective_stress": effective,
                "run": run,
                "config": cfg,
                **(extra_context or {}),
            }
        )

        status = RunStatus.COMPLETED
        for spec in pipeline.steps:
            if spec.step is None:
                sink.info("STEP_NO_CODE", f"module '{spec.id}' declares no step; skipped")
                continue
            try:
                result = spec.step(ctx)
            except Exception as exc:
                sink.error("STEP_CRASHED", f"module '{spec.id}' raised {exc!r}")
                if not spec.optional:
                    status = RunStatus.FAILED
                continue
            sink.extend(result.diagnostics)
            missing = [c for c in spec.provides if c not in result.outputs]
            if missing:
                sink.warning(
                    "STEP_INCOMPLETE",
                    f"module '{spec.id}' did not provide: {', '.join(missing)}",
                )
            ctx = ctx.with_outputs(result.outputs)

        if sink.has_errors and status is RunStatus.COMPLETED and not pipeline.steps:
            status = RunStatus.FAILED
        self.diags.add_many(run.id, sink.items)
        finished = self.runs.finish(run.id, status)
        return RunOutcome(run=finished, pipeline=pipeline, context=ctx, diagnostics=list(sink))


def summarize(diagnostics: Iterable[Diagnostic]) -> dict[str, int]:
    counts = dict.fromkeys((s.value for s in Severity), 0)
    for d in diagnostics:
        counts[d.severity.value] += 1
    return counts
