"""RKM and SI component-value parsing (PRD 3.1, BOM-03).

Accepts the notations found in CAD BOMs: ``4u7``, ``4.7uF``, ``4.7µF``, ``100n``, ``0R1``,
``2k2``, ``10m``, ``1/10W``, ``86.35MOHM``, ``22UF``. Returns an SI magnitude and the
coherent SI unit via :mod:`dfr.core.units`. Never raises on malformed text: returns ``None``
so callers can emit a Diagnostic.

Milli/mega ambiguity: lowercase ``m`` is always milli. Uppercase ``M`` is mega
(``1M``, ``1MOhm``) unless the unit that follows is written in vendor shout-case
(``86.35MOHM``, ``200MW``), where it means milli.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from dfr.core.units import UnitError, to_si

_PREFIXES: dict[str, float] = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "\u00b5": 1e-6,  # MICRO SIGN
    "\u03bc": 1e-6,  # GREEK SMALL LETTER MU
    "k": 1e3,
    "g": 1e9,
}

_UNIT_ALIASES: dict[str, str] = {
    "f": "F",
    "farad": "F",
    "h": "H",
    "henry": "H",
    "ohm": "ohm",
    "ohms": "ohm",
    "r": "ohm",
    "\u03a9": "ohm",
    "\u2126": "ohm",
    "v": "V",
    "volt": "V",
    "volts": "V",
    "a": "A",
    "amp": "A",
    "amps": "A",
    "w": "W",
    "watt": "W",
    "watts": "W",
    "hz": "Hz",
    "degc": "degC",
    "\u00b0c": "degC",
    "c": "C",  # coulomb (gate charge "125 nC"); temperatures use degC/°C
}

_LETTERS = r"A-Za-z\u00b5\u03bc\u03a9\u2126\u00b0"
_RKM_RE = re.compile(
    rf"^(?P<int>\d+)(?P<letter>[pnu\u00b5\u03bcmkKMGR])(?P<frac>\d+)(?P<unit>[{_LETTERS}]*)$"
)
_R_RE = re.compile(r"^(?P<int>\d+)R(?P<frac>\d*)$")
_PLAIN_RE = re.compile(rf"^(?P<num>\d+(?:\.\d+)?(?:/\d+)?|\.\d+)(?P<rest>[{_LETTERS}]*)$")


@dataclass(frozen=True)
class ParsedValue:
    magnitude: float  # in coherent SI unit
    unit: str  # "F", "H", "ohm", "V", "A", "W", "Hz", "K", "C" or "" when no unit given
    raw: str


def parse_value(  # noqa: PLR0911 - one return per notation branch
    text: str | None, *, default_unit: str | None = None
) -> ParsedValue | None:
    """Parse a component value. ``default_unit`` applies when the text carries none ("100n").

    Returns None for text that is not a value (empty, "DNP", "NC", garbage).
    """
    if text is None:
        return None
    raw = text.strip()
    compact = raw.replace(" ", "")
    if not compact:
        return None

    if m := _R_RE.match(compact):
        return _finish(float(f"{m.group('int')}.{m.group('frac') or '0'}"), "ohm", raw)

    if m := _RKM_RE.match(compact):
        number = float(f"{m.group('int')}.{m.group('frac')}")
        unit_text = m.group("unit")
        unit = _unit_for(unit_text) if unit_text else (default_unit or "")
        if unit_text and unit is None:
            return None
        factor = _prefix_factor(m.group("letter"), shout=unit_text.isupper())
        if factor is None:
            return None
        return _finish(number * factor, unit or "", raw)

    if m := _PLAIN_RE.match(compact):
        num_text, rest = m.group("num"), m.group("rest")
        number = float(Fraction(num_text)) if "/" in num_text else float(num_text)
        split = _split_prefix_unit(rest, default_unit)
        if split is None:
            return None
        factor, unit = split
        return _finish(number * factor, unit, raw)

    return None


def _finish(value: float, unit: str, raw: str) -> ParsedValue | None:
    if not unit:
        return ParsedValue(_clean(value), "", raw)
    try:
        mag, si_unit = to_si(value, unit)
    except UnitError:
        return None
    return ParsedValue(_clean(mag), si_unit, raw)


def _clean(x: float) -> float:
    """Drop binary noise from prefix multiplication (4.7 * 1e-6 -> 4.7e-06 exactly)."""
    return float(f"{x:.12g}")


def _unit_for(text: str) -> str | None:
    return _UNIT_ALIASES.get(text.lower())


def _prefix_factor(letter: str, *, shout: bool) -> float | None:
    if letter == "m":
        return 1e-3
    if letter == "M":
        return 1e-3 if shout else 1e6
    return _PREFIXES.get(letter.lower())


def _split_prefix_unit(rest: str, default_unit: str | None) -> tuple[float, str] | None:
    """'uF' -> (1e-6, 'F'); 'MOHM' -> (1e-3, 'ohm'); 'k' -> (1e3, default); '' -> (1, default)."""
    if not rest:
        return 1.0, default_unit or ""
    whole = _unit_for(rest)
    if whole is not None:
        return 1.0, whole
    first, tail = rest[0], rest[1:]
    if tail:
        unit = _unit_for(tail)
        if unit is None:
            return None
        factor = _prefix_factor(first, shout=tail.isupper())
    else:
        unit = default_unit or ""
        factor = _prefix_factor(first, shout=False)
    if factor is None:
        return None
    return factor, unit
