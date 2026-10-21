"""Converter spec, value prompts and run configuration (PRD sections 2.3, 3.2)."""

from __future__ import annotations

import json
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dfr.core.contracts.v1.enums import PromptOrigin, PromptStatus


class ConverterSpec(BaseModel):
    """User-entered operating point. Validation per OPC-04."""

    model_config = ConfigDict(frozen=True)

    vin_min: float = Field(gt=0)
    vin_max: float = Field(gt=0)
    vout: float
    iout_max: float = Field(gt=0)
    fsw: float = Field(gt=0)
    t_ambient: float = Field(gt=-273.15)

    @model_validator(mode="after")
    def _vin_range(self) -> ConverterSpec:
        if self.vin_min > self.vin_max:
            msg = "vin_min must not exceed vin_max"
            raise ValueError(msg)
        return self


class MissionProfile(BaseModel):
    """Usage assumptions for lifetime models (PRD 3.6/3.7). Additive v1 contract.

    Defaults describe continuous operation with one power cycle per day; every analysis shows
    the profile it used, so a default is an explicit assumption rather than a hidden guess.
    """

    model_config = ConfigDict(frozen=True)

    target_life_years: float = Field(default=10.0, gt=0)
    operating_hours_per_year: float = Field(default=8766.0, gt=0, le=8766.0)
    on_off_cycles_per_year: float = Field(default=365.0, ge=0)
    mating_cycles_per_year: float = Field(default=0.0, ge=0)
    t_ambient_off: float | None = None  # ambient when powered down; None = same as operating

    @property
    def target_life_hours(self) -> float:
        return self.target_life_years * 8766.0


class ValuePrompt(BaseModel):
    """A number the app needs but will not guess (PRD section 3.2 mode d)."""

    id: int | None = None
    part_id: int | None
    param: str
    stat: str
    scenario: str
    reason: str
    how_to_obtain: str
    origin: PromptOrigin
    status: PromptStatus = PromptStatus.OPEN


class RunConfig(BaseModel):
    """Everything that selects behaviour for one analysis run; stored verbatim in the run row."""

    model_config = ConfigDict(frozen=True)

    ruleset_id: str = "generic_conservative"
    failure_rate_method: str | None = None
    enabled_modules: tuple[str, ...] | None = None  # None = every discovered module
    iteration_cap: int = 3
    extra: dict[str, str] = Field(default_factory=dict)

    # Additive v1: the spec and mission profile a run was made with travel in ``extra`` as JSON
    # so a stored run (report, reopen) can recover them without the UI session.
    SPEC_KEY: ClassVar[str] = "converter_spec"
    PROFILE_KEY: ClassVar[str] = "mission_profile"
    OVERRIDES_KEY: ClassVar[str] = "inferred_overrides"

    def with_inputs(
        self,
        spec: ConverterSpec,
        profile: MissionProfile | None,
        overrides: dict[str, float] | None = None,
    ) -> RunConfig:
        extra = {
            **self.extra,
            self.SPEC_KEY: spec.model_dump_json(),
            self.PROFILE_KEY: (profile or MissionProfile()).model_dump_json(),
        }
        if overrides:
            extra[self.OVERRIDES_KEY] = json.dumps(overrides, sort_keys=True)
        return self.model_copy(update={"extra": extra})

    @property
    def inferred_overrides(self) -> dict[str, float]:
        raw = self.extra.get(self.OVERRIDES_KEY)
        return {k: float(v) for k, v in json.loads(raw).items()} if raw else {}

    @property
    def converter_spec(self) -> ConverterSpec | None:
        raw = self.extra.get(self.SPEC_KEY)
        return ConverterSpec.model_validate_json(raw) if raw else None

    @property
    def mission_profile(self) -> MissionProfile | None:
        raw = self.extra.get(self.PROFILE_KEY)
        return MissionProfile.model_validate_json(raw) if raw else None
