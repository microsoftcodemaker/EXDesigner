"""Build an ordered pipeline from ModuleSpec requires/provides (MOD-03, MOD-04).

Missing dependencies never raise: the dependent step is dropped with a Diagnostic and
everything else still runs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter

from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.contracts.v1.enums import Severity
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.registry.spec import ModuleSpec


@dataclass
class Pipeline:
    steps: list[ModuleSpec] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # module id -> reason
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return [s.id for s in self.steps]

    def provides(self) -> frozenset[str]:
        caps: set[str] = set()
        for s in self.steps:
            caps.update(s.provides)
        return frozenset(caps)


def build_pipeline(
    specs: Sequence[ModuleSpec],
    *,
    enabled: Iterable[str] | None = None,
    initial_capabilities: Iterable[str] = (),
) -> Pipeline:
    sink = DiagnosticSink("pipeline")
    pipeline = Pipeline()
    enabled_set = set(enabled) if enabled is not None else None

    candidates = {s.id: s for s in specs if enabled_set is None or s.id in enabled_set}
    for s in specs:
        if s.id not in candidates:
            pipeline.skipped[s.id] = "disabled by config"

    providers: dict[str, ModuleSpec] = {}
    for s in candidates.values():
        for cap in s.provides:
            if cap in providers:
                sink.error(
                    "PIPELINE_DUPLICATE_PROVIDER",
                    f"capability '{cap}' provided by both '{providers[cap].id}' and '{s.id}'; "
                    f"keeping '{providers[cap].id}'",
                )
                continue
            providers[cap] = s

    available = set(initial_capabilities)
    # Iteratively drop modules whose requirements cannot be met (handles transitive loss).
    active = dict(candidates)
    changed = True
    while changed:
        changed = False
        satisfiable = available | {c for s in active.values() for c in s.provides}
        for mid, spec in list(active.items()):
            missing = [c for c in spec.requires if c not in satisfiable]
            if missing:
                reason = f"missing required capability: {', '.join(missing)}"
                pipeline.skipped[mid] = reason
                sink.add(
                    "PIPELINE_MISSING_DEP",
                    f"module '{mid}' skipped: {reason}",
                    severity=Severity.WARNING if spec.optional else Severity.ERROR,
                )
                del active[mid]
                changed = True

    sorter: TopologicalSorter[str] = TopologicalSorter()
    for mid, spec in active.items():
        deps = {
            providers[c].id for c in spec.requires if c in providers and providers[c].id in active
        }
        sorter.add(mid, *deps)
    try:
        order = list(sorter.static_order())
    except CycleError as exc:
        cycle = " -> ".join(exc.args[1]) if len(exc.args) > 1 else "?"
        sink.error("PIPELINE_CYCLE", f"dependency cycle: {cycle}; pipeline is empty")
        for mid in active:
            pipeline.skipped[mid] = "dependency cycle"
        order = []

    pipeline.steps = [active[mid] for mid in order]
    pipeline.diagnostics = list(sink.items)
    return pipeline
