from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError

from dfr.core import contracts as c
from dfr.core.contracts import v1

PRD_EXAMPLE = {
    "part_id": 12,
    "param": "i_rms",
    "value": 3.42,
    "unit": "A",
    "stat": "rms",
    "scenario": "vin_max",
    "source": "equation",
    "tier": 1,
    "tool": "topology.buck@1.0.0",
    "tool_version": "1.0.0",
    "timestamp": "2026-10-18T14:02:11Z",
    "pinned": False,
}


def test_prd_stress_value_example_parses() -> None:
    sv = c.StressValue.model_validate(PRD_EXAMPLE)
    assert sv.tier is c.Tier.T1
    assert sv.source is c.Source.EQUATION
    assert sv.key == c.StressKey(12, "i_rms", "vin_max")


def test_stress_value_rejects_unknown_unit() -> None:
    with pytest.raises(ValidationError):
        c.StressValue.model_validate({**PRD_EXAMPLE, "unit": "amperes_of_doom"})


def test_stress_value_is_frozen() -> None:
    sv = c.StressValue.model_validate(PRD_EXAMPLE)
    with pytest.raises(ValidationError):
        sv.value = 1.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "name",
    [n for n in v1.__all__ if n != "API_VERSION" and n != "StressKey"],
)
def test_every_contract_round_trips_json_schema(name: str) -> None:
    obj = getattr(v1, name)
    if isinstance(obj, type) and issubclass(obj, BaseModel):
        schema = obj.model_json_schema()
        assert json.dumps(schema)  # serializable


def test_converter_spec_validation() -> None:
    ok = c.ConverterSpec(vin_min=20, vin_max=28, vout=5, iout_max=3, fsw=500e3, t_ambient=25)
    assert ok.vin_max == 28
    with pytest.raises(ValidationError):
        c.ConverterSpec(vin_min=30, vin_max=28, vout=5, iout_max=3, fsw=500e3, t_ambient=25)
    with pytest.raises(ValidationError):
        c.ConverterSpec(vin_min=20, vin_max=28, vout=5, iout_max=3, fsw=0, t_ambient=25)


def test_lifetime_result_not_available_is_none_not_zero() -> None:
    r = c.LifetimeResult(
        part_id=1,
        mechanism="dry_out",
        model_id="elko@1",
        life_hours=None,
        confidence=c.Confidence.LOW,
    )
    assert r.life_years is None
    assert c.LifetimeResult(
        part_id=1, mechanism="x", model_id="y", life_hours=8766.0, confidence=c.Confidence.HIGH
    ).life_years == pytest.approx(1.0)


def test_fmea_rpn() -> None:
    row = c.FmeaRow(
        part_id=1,
        mode="short",
        local_effect="a",
        system_effect="b",
        severity=7,
        occurrence=3,
        detection=4,
    )
    assert row.rpn == 84


def test_diagnostic_str() -> None:
    d = c.Diagnostic(code="X", severity=c.Severity.ERROR, message="m", module="m1", line_no=4)
    assert str(d) == "[m1] ERROR X (line 4): m"


def test_contracts_namespace_tracks_current_version() -> None:
    assert c.CURRENT is v1
    assert c.API_VERSION == "1"
    assert c.StressValue is v1.StressValue
