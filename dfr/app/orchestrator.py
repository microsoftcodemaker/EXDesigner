"""Orchestrator: sequences registry-built pipeline steps on an immutable run (PRD section 2.6).

It knows no module by name. Steps come from ``build_pipeline`` and exchange data only
through the capability bag (``RunContext``). Each run is persisted before any step runs
and frozen (``finish``) afterwards, with every diagnostic stored against it.

Persistence stays with the module that owns the table: after a step, its optional
``persist(session, run_id, result)`` hook stores rows and may return replacement outputs
(e.g. stress values now carrying ids). When a step provides ``stress``, the effective
stress map is re-resolved so downstream steps see the new Tier 1 values.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from dfr.core.contracts import (
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
from dfr.core.registry import ModuleSpec, Pipeline, RunContext, StepResult, build_pipeline

# Capabilities the orchestrator itself seeds before any module step runs.
SEED_CAPABILITIES = ("parts", "effective_stress", "run", "config", "clock")


@dataclass
class RunOutcome:
    run: AnalysisRun
    pipeline: Pipeline
    context: RunContext
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.run.status is RunStatus.COMPLETED


def plan_pipeline(
    specs: Sequence[ModuleSpec], cfg: RunConfig, extra_capabilities: Iterable[str] = ()
) -> Pipeline:
    """The step order the orchestrator would use for ``cfg``; no database needed.

    Service-only modules (no ``step``) are not pipeline steps and are left out.
    """
    return build_pipeline(
        [s for s in specs if s.step is not None],
        enabled=cfg.enabled_modules,
        initial_capabilities=(*SEED_CAPABILITIES, *extra_capabilities),
    )


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

    def plan(self, cfg: RunConfig, extra_capabilities: Iterable[str] = ()) -> Pipeline:
        return plan_pipeline(self.specs, cfg, extra_capabilities)

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
        extra = dict(extra_context or {})
        pipeline = self.plan(cfg, extra)
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
        run_id = run.id

        parts = self.parts.for_version(design_version_id, include_dnp=False)
        override_list = list(overrides or [])
        if any(v.id is None for v in override_list):
            sink.warning(
                "RUN_UNPERSISTED_OVERRIDES",
                "some override stress values are not stored; they are used but not snapshotted",
            )
        effective = resolve_effective_stress(
            [*self.stress.for_version(design_version_id), *override_list]
        )
        ctx = RunContext(
            {
                "parts": parts,
                "effective_stress": effective,
                "run": run,
                "config": cfg,
                "clock": self.clock,
                **extra,
            }
        )

        status = RunStatus.COMPLETED
        for spec in pipeline.steps:
            if spec.step is None:
                sink.info("STEP_NO_CODE", f"module '{spec.id}' declares no step; skipped")
                continue
            try:
                result = spec.step(ctx)
            except Exception as exc:  # a module must never take down the run
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
            outputs = dict(result.outputs)
            if spec.persist is not None:
                try:
                    replaced = spec.persist(self.session, run_id, result)
                except Exception as exc:
                    sink.error("STEP_PERSIST_FAILED", f"module '{spec.id}' persist raised {exc!r}")
                    replaced = None
                if replaced:
                    outputs.update(replaced)
            ctx = ctx.with_outputs(outputs)
            if "stress" in outputs:
                ctx = ctx.with_outputs(
                    {
                        "effective_stress": resolve_effective_stress(
                            [*self.stress.for_version(design_version_id), *override_list]
                        )
                    }
                )

        if sink.has_errors and status is RunStatus.COMPLETED and not pipeline.steps:
            status = RunStatus.FAILED
        final_effective: dict[Any, StressValue] = ctx.get("effective_stress")
        self.runs.snapshot_effective(
            run_id, {k: v for k, v in final_effective.items() if v.id is not None}
        )
        self.diags.add_many(run_id, sink.items)
        finished = self.runs.finish(run_id, status)
        return RunOutcome(run=finished, pipeline=pipeline, context=ctx, diagnostics=list(sink))


def summarize(diagnostics: Iterable[Diagnostic]) -> dict[str, int]:
    counts = dict.fromkeys((s.value for s in Severity), 0)
    for d in diagnostics:
        counts[d.severity.value] += 1
    return counts


__all__ = [
    "SEED_CAPABILITIES",
    "Orchestrator",
    "RunOutcome",
    "StepResult",
    "plan_pipeline",
    "summarize",
]
