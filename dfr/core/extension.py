"""Extension-point interfaces (PRD section 2.5 and 2.7 rules 9-12).

Implementations live in module/topology folders or external plugins and are discovered
through the registry. ``dfr.api`` re-exports these for plugin authors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.contracts.v1.netlist import NetlistGraph
from dfr.core.contracts.v1.part import Part
from dfr.core.contracts.v1.results import LifetimeResult, ThermalResult
from dfr.core.contracts.v1.stress import StressValue
from dfr.core.contracts.v1.topology import PatternMatch, RoleProposal

# --------------------------------------------------------------------------- topologies


class TopologyPattern(ABC):
    """M12: finds a converter stage in the netlist graph and proposes roles and rails."""

    id: str
    version: str
    roles: tuple[str, ...]
    rails: tuple[str, ...]

    @abstractmethod
    def match(self, graph: NetlistGraph, parts: Sequence[Part]) -> list[PatternMatch]: ...

    @abstractmethod
    def propose(self, match: PatternMatch, parts: Sequence[Part]) -> RoleProposal: ...


class TopologyTemplate(ABC):
    """M2: closed-form Tier 1 stress equations for one topology. Pairs with a pattern."""

    id: str
    version: str
    pattern_id: str
    required_inputs: tuple[str, ...]
    roles: tuple[str, ...]

    @abstractmethod
    def validity_checks(self, params: Mapping[str, float]) -> list[Diagnostic]: ...

    @abstractmethod
    def compute(self, params: Mapping[str, float]) -> dict[str, list[StressValue]]:
        """Return stress values keyed by role."""


# --------------------------------------------------------------------------- models


class LifetimeModel(ABC):
    """M7 plugin: one wear-out mechanism."""

    id: str
    version: str
    mechanism: str

    @abstractmethod
    def applies_to(self, part: Part) -> bool: ...

    @abstractmethod
    def estimate(
        self,
        part: Part,
        stress: Sequence[StressValue],
        thermal: ThermalResult | None,
        profile: Any,
    ) -> LifetimeResult: ...


class FailureRateModel(ABC):
    """M8 plugin: one failure-rate method."""

    id: str
    version: str

    @abstractmethod
    def applies_to(self, part: Part) -> bool: ...

    @abstractmethod
    def rate(self, part: Part, ctx: Mapping[str, Any]) -> float:
        """Failure rate in FIT."""


# --------------------------------------------------------------------------- UI / report


class ScreenSpec(BaseModel):
    """A GUI screen registered by a module. The stepper is built from these (MOD-06)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str
    title: str
    step: str  # stepper group: design / parts / circuit / conditions / analyze / refine / report
    order: int = 100
    requires: tuple[str, ...] = ()  # module ids that must be present
    factory: Callable[..., Any] | None = None  # (view_model) -> QWidget; None in headless runs


class ReportSectionSpec(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str
    title: str
    order: int
    requires: tuple[str, ...] = ()
    render: Callable[..., str] | None = None  # (run_bundle) -> HTML fragment


class ChartSpec(BaseModel):
    """One chart definition rendered identically by the GUI canvas and the report."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str  # bar / hbar / line / heatmap / histogram / tornado
    title: str
    x_label: str = ""
    y_label: str = ""
    options: dict[str, Any] = Field(default_factory=dict)
