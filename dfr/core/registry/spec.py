"""ModuleSpec and the runtime step protocol (PRD section 2.7 rules 2-4).

A module folder ships ``module.py`` exposing ``MODULE: ModuleSpec``. The orchestrator
builds its pipeline from ``requires``/``provides`` capability names and never imports a
module directly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.diagnostics import DiagnosticSink


class RunContext:
    """Capability bag passed to each step. Read-only view of what earlier steps provided."""

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})

    def get(self, capability: str) -> Any:
        return self._data[capability]

    def get_or(self, capability: str, default: Any = None) -> Any:
        return self._data.get(capability, default)

    def has(self, capability: str) -> bool:
        return capability in self._data

    def with_outputs(self, outputs: Mapping[str, Any]) -> RunContext:
        merged = dict(self._data)
        merged.update(outputs)
        return RunContext(merged)

    def capabilities(self) -> frozenset[str]:
        return frozenset(self._data)


class StepResult(BaseModel):
    """What a pipeline step returns: one object per provided capability plus diagnostics."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    outputs: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @classmethod
    def from_sink(cls, sink: DiagnosticSink, **outputs: Any) -> StepResult:
        return cls(outputs=outputs, diagnostics=list(sink.items))


StepFn = Callable[[RunContext], StepResult]
# persist(session, run_id, result) -> replacement outputs (e.g. stored rows with ids) or None
PersistFn = Callable[[Any, int, StepResult], Mapping[str, Any] | None]


class ModuleSpec(BaseModel):
    """Declarative description of one module or topology plugin."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str = Field(pattern=r"^[a-z_][a-z0-9_]*$")
    name: str
    version: str
    api_version: str
    requires: tuple[str, ...] = ()
    optional_requires: tuple[str, ...] = ()  # ordering only; absence is not a diagnostic
    provides: tuple[str, ...] = ()
    optional: bool = True
    step: StepFn | None = None
    persist: PersistFn | None = None
    services: dict[str, Callable[..., Any]] = Field(default_factory=dict)
    migrations_path: Path | None = None
    table_prefix: str | None = None

    @property
    def tool_tag(self) -> str:
        """Provenance stamp written on every value this module produces (PRD section 2.5)."""
        return f"{self.id}@{self.version}"


class ServiceNotFound(LookupError):
    """A named service is not provided by any discovered module (the module is absent)."""
