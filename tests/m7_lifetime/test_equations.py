"""Hand-calculated cases for the PRD 3.7 equations (>= 3 per equation, 0.1 % tolerance)."""

from __future__ import annotations

import pytest

from dfr.modules.m7_lifetime.equations import (
    coffin_manson_cycles,
    connector_life_hours,
    core_temperature,
    miner_life_hours,
    prokopowicz_vaskas_life_hours,
    temperature_rule_life_hours,
)

REL = 1e-3


@pytest.mark.parametrize(
    ("l0", "t0", "t_core", "k", "expected"),
    [
        (5000, 105, 65, 10, 80000),  # 4 doublings: 5000 * 2^4
        (5000, 105, 105, 10, 5000),  # at rated temperature
        (5000, 105, 115, 10, 2500),  # 10 K above rated: halved (extrapolated)
        (5000, 105, 85, 20, 10000),  # polymer-style 20-degree rule: one doubling
    ],
)
def test_temperature_rule(l0, t0, t_core, k, expected) -> None:
    assert temperature_rule_life_hours(l0, t0, t_core, k) == pytest.approx(expected, rel=REL)


@pytest.mark.parametrize(
    ("ta", "dt0", "i", "i_rated", "expected"),
    [
        (45, 5, 1.0, 2.0, 46.25),  # 45 + 5 * 0.5^2
        (45, 5, 2.0, 2.0, 50.0),  # rated ripple: full core rise
        (45, 5, 0.0, 2.0, 45.0),  # no ripple
    ],
)
def test_core_temperature(ta, dt0, i, i_rated, expected) -> None:
    assert core_temperature(ta, dt0, i, i_rated) == pytest.approx(expected, rel=REL)


@pytest.mark.parametrize(
    ("v2", "t2", "n", "ea", "expected"),
    [
        (50, 125, 3, 1.2, 8000),  # same temperature: (100/50)^3
        (100, 85, 3, 1.2, 49718.19),  # same voltage: exp(13925.96 * (1/358.15 - 1/398.15))
        (50, 45, 3, 1.1, 25375436.5),  # both: 8 * exp(12765.5 * (1/318.15 - 1/398.15))
    ],
)
def test_prokopowicz_vaskas(v2, t2, n, ea, expected) -> None:
    life = prokopowicz_vaskas_life_hours(1000, 100, 125, v2, t2, n, ea, 8.617e-5)
    assert life == pytest.approx(expected, rel=REL)


def test_coffin_manson_and_miner() -> None:
    assert coffin_manson_cycles(3e11, 5, 50) == pytest.approx(960.0, rel=REL)  # 3e11 / 50^5
    assert coffin_manson_cycles(3e11, 5, 100) == pytest.approx(30.0, rel=REL)  # 3e11 / 1e10
    assert coffin_manson_cycles(1e11, 4, 100) == pytest.approx(1000.0, rel=REL)
    # D = 365/960 per year -> life = 8766 / 0.380208
    assert miner_life_hours([(50, 365)], 3e11, 5) == pytest.approx(23055.78, rel=REL)
    # two bins: 365/960 + 10/30 = 0.713542
    assert miner_life_hours([(50, 365), (100, 10)], 3e11, 5) == pytest.approx(12285.2, rel=REL)
    # swings below the threshold and empty bins count no damage
    assert miner_life_hours([(50, 365)], 3e11, 5, min_delta_tj=60) is None
    assert miner_life_hours([(50, 0), (-5, 10)], 3e11, 5) is None


def test_connector_and_input_validation() -> None:
    assert connector_life_hours(500, 50) == pytest.approx(87660.0, rel=REL)  # 10 years
    assert connector_life_hours(1000, 100) == pytest.approx(87660.0, rel=REL)
    assert connector_life_hours(100, 400) == pytest.approx(2191.5, rel=REL)  # 0.25 years
    assert connector_life_hours(500, 0) is None
    for bad in (
        lambda: connector_life_hours(0, 1),
        lambda: core_temperature(25, 5, 1, 0),
        lambda: temperature_rule_life_hours(0, 105, 65, 10),
        lambda: prokopowicz_vaskas_life_hours(1000, 100, 125, 0, 25, 3, 1.2, 8.617e-5),
        lambda: coffin_manson_cycles(3e11, 5, 0),
    ):
        with pytest.raises(ValueError):
            bad()
