from __future__ import annotations

import pytest

from dfr.core.values import parse_value

CASES: list[tuple[str, str | None, float, str]] = [
    # RKM (unit letter replaces decimal point)
    ("4u7", "F", 4.7e-6, "F"),
    ("4u7F", None, 4.7e-6, "F"),
    ("2k2", "ohm", 2200.0, "ohm"),
    ("0R1", None, 0.1, "ohm"),
    ("1R0", None, 1.0, "ohm"),
    ("4R7", None, 4.7, "ohm"),
    ("1M5", "ohm", 1.5e6, "ohm"),
    ("4n7", "F", 4.7e-9, "F"),
    ("3m3", "H", 3.3e-3, "H"),
    ("2\u00b52", "F", 2.2e-6, "F"),  # micro sign as RKM letter
    # plain with prefix and unit
    ("4.7uF", None, 4.7e-6, "F"),
    ("4.7\u00b5F", None, 4.7e-6, "F"),
    ("4.7\u03bcF", None, 4.7e-6, "F"),
    ("22UF", None, 22e-6, "F"),
    ("0.22UF", None, 0.22e-6, "F"),
    ("100nF", None, 1e-7, "F"),
    ("100pF", None, 1e-10, "F"),
    ("10UH", None, 10e-6, "H"),
    ("10 uH", None, 10e-6, "H"),
    ("1mH", None, 1e-3, "H"),
    ("10k", "ohm", 10e3, "ohm"),
    ("10K", "ohm", 10e3, "ohm"),
    ("4.75K OHM", None, 4750.0, "ohm"),
    ("88.7K OHM", None, 88700.0, "ohm"),
    ("130 OHM", None, 130.0, "ohm"),
    ("0.015 OHM", None, 0.015, "ohm"),
    ("86.35MOHM", None, 0.08635, "ohm"),  # vendor caps: milli
    ("4.1 mOhm", None, 4.1e-3, "ohm"),
    ("1MOhm", None, 1e6, "ohm"),
    ("1M", "ohm", 1e6, "ohm"),
    ("10m", "ohm", 10e-3, "ohm"),
    ("50V", None, 50.0, "V"),
    ("3.3V", None, 3.3, "V"),
    ("4.2A", None, 4.2, "A"),
    ("200MW", None, 0.2, "W"),
    ("200mW", None, 0.2, "W"),
    ("1/10W", None, 0.1, "W"),
    ("1/16W", None, 0.0625, "W"),
    ("500kHz", None, 5e5, "Hz"),
    ("125 nC", None, 125e-9, "C"),
    # no unit, no default
    ("100n", None, 1e-7, ""),
    ("47", None, 47.0, ""),
    # default unit applied
    ("100n", "F", 1e-7, "F"),
    ("47", "ohm", 47.0, "ohm"),
]


@pytest.mark.parametrize(("text", "default", "mag", "unit"), CASES)
def test_parse_value(text: str, default: str | None, mag: float, unit: str) -> None:
    got = parse_value(text, default_unit=default)
    assert got is not None, text
    assert got.magnitude == pytest.approx(mag, rel=1e-9), text
    assert got.unit == unit, text
    assert got.raw == text.strip()


@pytest.mark.parametrize("text", ["", "   ", "DNP", "NC", "abc", "10X", "k10", "--", "1.2.3"])
def test_non_values_return_none(text: str) -> None:
    assert parse_value(text) is None


def test_case_count_meets_prd_table() -> None:
    assert len(CASES) >= 40
