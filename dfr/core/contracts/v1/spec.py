"""Converter spec, value prompts and run configuration (PRD sections 2.3, 3.2)."""

from __future__ import annotations

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
