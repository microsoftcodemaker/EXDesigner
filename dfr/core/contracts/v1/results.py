"""Result row shapes produced by M3, M5-M9 (PRD sections 3.3-3.9). Producers arrive later."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dfr.core.contracts.v1.enums import Confidence, DeratingStatus
from dfr.core.contracts.v1.spec import ValuePrompt


class DeratingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    part_id: int
    param: str
    stress: float | None
    limit: float | None
    rating: float | None
    ratio: float | None
    status: DeratingStatus
    margin: float | None
    rule_id: str
    stress_value_ids: tuple[int, ...] = ()


class ThermalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    part_id: int
    scenario: str
    tj: float
    tc: float | None = None
    delta_tj_cycles: tuple[tuple[float, float, float], ...] = ()  # (dTj, Tj_mean, count)
    runaway_flag: bool = False
    stress_value_ids: tuple[int, ...] = ()


class LifetimeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    part_id: int
    mechanism: str
    model_id: str
    life_hours: float | None  # None = "not available", never zero or guessed
    confidence: Confidence
    assumptions: tuple[str, ...] = ()
    input_stress_ids: tuple[int, ...] = ()

    @property
    def life_years(self) -> float | None:
        return None if self.life_hours is None else self.life_hours / 8766.0


class PartFailureRate(BaseModel):
    model_config = ConfigDict(frozen=True)

    part_id: int
    lambda_fit: float
    factors: dict[str, float] = Field(default_factory=dict)


class FailureRateResult(BaseModel):
    method: str
    per_part: list[PartFailureRate] = Field(default_factory=list)
    system_lambda_fit: float | None = None
    system_mtbf_h: float | None = None
    reliability_curve: list[tuple[float, float]] | None = None  # (t_hours, R)
    assumptions: list[str] = Field(default_factory=list)
    excluded_part_ids: list[int] = Field(default_factory=list)
    # Additive v1 (M8): wear-out roll-ups report MTTF and B10 instead of an MTBF (MTB-04);
    # every result names the table it used and that table's confidence.
    system_mttf_h: float | None = None
    b10_h: float | None = None
    table_id: str | None = None
    confidence: Confidence | None = None
    excluded_reasons: dict[int, str] = Field(default_factory=dict)


class RefinementItem(BaseModel):
    id: int | None = None  # database id once persisted (additive, v1)
    part_id: int
    flags: list[str]
    reasons: list[str]
    score: float
    parameters_to_refine: list[str] = Field(default_factory=list)
    recommended_scenarios: list[str] = Field(default_factory=list)
    prompts: list[ValuePrompt] = Field(default_factory=list)
    status: str = "open"  # open / refined / waived
    waiver_reason: str | None = None


class FmeaRow(BaseModel):
    part_id: int
    mode: str
    local_effect: str
    system_effect: str
    severity: int = Field(ge=1, le=10)
    occurrence: int = Field(ge=1, le=10)
    detection: int = Field(ge=1, le=10)
    source_flags: dict[str, str] = Field(default_factory=dict)  # S/O/D -> "seed" | "user"
    mitigation_note: str | None = None
    # Additive v1 (M9): db id, the library mode id (override key with part_id), how O was
    # derived ("fit" | "life" | "no_data" | "user") and the inputs behind it.
    id: int | None = None
    mode_id: str = ""
    occurrence_basis: str = ""
    lambda_fit: float | None = None
    life_ratio: float | None = None

    @property
    def rpn(self) -> int:
        return self.severity * self.occurrence * self.detection


class AnalysisResults(BaseModel):
    """Bundle handed to triage and reporting."""

    derating: list[DeratingResult] = Field(default_factory=list)
    thermal: list[ThermalResult] = Field(default_factory=list)
    lifetime: list[LifetimeResult] = Field(default_factory=list)
    failure_rate: FailureRateResult | None = None
