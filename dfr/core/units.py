"""Single pint registry for the whole app. Prevents micro/milli/mega confusion (PRD section 2.4).

Only this module imports pint. Everything else calls the helpers below.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import pint

# Characters users and CAD tools substitute for the micro sign.
_MICRO_ALIASES = {"\u00b5": "u", "\u03bc": "u"}  # MICRO SIGN, GREEK SMALL LETTER MU

# Unit strings that are not pint units but appear constantly in BOMs/CSVs.
_SPELLINGS = {
    "degC": "degC",
    "°C": "degC",
    "ohm": "ohm",
    "Ohm": "ohm",
    "Ω": "ohm",
    "R": "ohm",
    "%": "percent",
}


class UnitError(ValueError):
    """Raised when a unit string is unknown or incompatible."""


@lru_cache(maxsize=1)
def registry() -> pint.UnitRegistry:
    ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
    ureg.define("FIT = 1e-9 / hour")
    ureg.define("percent = 0.01 = %")
    return ureg


def normalize_unit(unit: str) -> str:
    """Map common spellings and micro-sign variants to pint-parsable text."""
    text = unit.strip()
    for bad, good in _MICRO_ALIASES.items():
        text = text.replace(bad, good)
    return _SPELLINGS.get(text, text)


def validate_unit(unit: str) -> None:
    """Raise :class:`UnitError` if ``unit`` is not something pint understands."""
    try:
        registry().parse_units(normalize_unit(unit))
    except Exception as exc:  # pint raises several unrelated types
        msg = f"Unknown unit {unit!r}"
        raise UnitError(msg) from exc


def quantity(value: float, unit: str) -> Any:
    """Build a pint quantity; ``unit`` may use any accepted spelling."""
    validate_unit(unit)
    return registry().Quantity(value, normalize_unit(unit))


_PREFERRED_SI = ("F", "H", "ohm", "V", "A", "W", "J", "C", "Hz", "s", "K", "m", "kg")


@lru_cache(maxsize=1)
def _preferred_by_dimension() -> dict[str, str]:
    ureg = registry()
    return {str(ureg.Unit(u).dimensionality): u for u in _PREFERRED_SI}


def to_si(value: float, unit: str) -> tuple[float, str]:
    """Convert to the coherent SI unit (4.7 uF -> (4.7e-6, 'F')). Returns ``(magnitude, unit)``.

    Dimensions without a preferred unit fall back to pint's base-unit expansion.
    Temperatures are returned in kelvin.
    """
    q = quantity(value, unit)
    target = _preferred_by_dimension().get(str(q.dimensionality))
    q = q.to(target) if target else q.to_base_units()
    return float(q.magnitude), f"{q.units:~}".replace("\u03a9", "ohm")


def convert(value: float, unit: str, target: str) -> float:
    """Convert ``value`` from ``unit`` to ``target``; raises :class:`UnitError` if incompatible."""
    try:
        return float(quantity(value, unit).to(normalize_unit(target)).magnitude)
    except pint.DimensionalityError as exc:
        msg = f"Cannot convert {unit!r} to {target!r}"
        raise UnitError(msg) from exc
