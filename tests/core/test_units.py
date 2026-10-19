from __future__ import annotations

import pytest

from dfr.core.units import UnitError, convert, normalize_unit, to_si, validate_unit


@pytest.mark.parametrize(
    ("value", "unit", "expected", "si_unit"),
    [
        (4.7, "uF", 4.7e-6, "F"),
        (4.7, "\u00b5F", 4.7e-6, "F"),  # MICRO SIGN
        (4.7, "\u03bcF", 4.7e-6, "F"),  # GREEK MU
        (100, "nF", 1e-7, "F"),
        (2.2, "kohm", 2200.0, "ohm"),
        (86.35, "mohm", 0.08635, "ohm"),
        (10, "mH", 0.01, "H"),
        (500, "kHz", 5e5, "Hz"),
        (3, "A", 3.0, "A"),
        (1000, "mA", 1.0, "A"),
        (25, "degC", 298.15, "K"),
    ],
)
def test_to_si(value: float, unit: str, expected: float, si_unit: str) -> None:
    mag, u = to_si(value, unit)
    assert mag == pytest.approx(expected)
    assert u == si_unit


def test_prefix_invariance() -> None:
    assert to_si(1000, "mA")[0] == pytest.approx(to_si(1, "A")[0])


def test_validate_unit_rejects_garbage() -> None:
    with pytest.raises(UnitError):
        validate_unit("furlongs_per_fortnight_squared!")


def test_convert_incompatible_raises() -> None:
    with pytest.raises(UnitError):
        convert(1, "A", "V")


def test_fit_defined() -> None:
    validate_unit("FIT")
    assert convert(1e9, "FIT", "1/hour") == pytest.approx(1.0)


def test_normalize_spellings() -> None:
    assert normalize_unit("\u03a9") == "ohm"
    assert normalize_unit("\u00b0C") == "degC"
    assert normalize_unit("%") == "percent"
