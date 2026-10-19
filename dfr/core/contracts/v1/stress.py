"""StressValue: the core exchange type (PRD section 2.3)."""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dfr.core.contracts.v1.enums import Scenario, Source, Stat, Tier
from dfr.core.units import validate_unit


class StressKey(NamedTuple):
    part_id: int
    param: str
    scenario: str


class StressValue(BaseModel):
    """One stressed parameter of one part, with full provenance. Immutable once stored."""

    model_config = ConfigDict(frozen=True)

    id: int | None = None
    part_id: int
    param: str  # "i_rms", "i_peak", "v_peak", "v_dc", "p_loss", "t_ambient", ...
    value: float
    unit: str
    stat: Stat
    scenario: str = Scenario.NOMINAL.value
    source: Source
    tier: Tier
    tool: str  # "topology.buck@1.0.0", "csv:scope.csv", "prompt:user"
    tool_version: str
    timestamp: datetime
    pinned: bool = False
    note: str | None = None

    @field_validator("unit")
    @classmethod
    def _unit_is_known(cls, v: str) -> str:
        validate_unit(v)
        return v

    @property
    def key(self) -> StressKey:
        return StressKey(self.part_id, self.param, self.scenario)


class InferredValue(BaseModel):
    """A value inferred from the BOM through roles (L, Cout, ESR_eq) with contributing refdes."""

    model_config = ConfigDict(frozen=True)

    name: str
    value: float
    unit: str
    provenance: str = "bom"  # "bom" or "user" (override)
    contributing_refdes: tuple[str, ...] = ()
    note: str | None = None


class InferredValues(BaseModel):
    values: dict[str, InferredValue] = Field(default_factory=dict)
