"""Extract value and ratings from vendor description text (PRD 3.1, BOM-11).

Examples from the Design C BomDoc:
    "CAP CER 0.22UF 50V X7R 0805"          -> 0.22 uF, v_rated 50 V, X7R, 0805
    "FIXED IND 10UH 4.2A 86.35MOHM SM"      -> 10 uH, i_rated 4.2 A, dcr 86.35 mohm
    "RES SMD 88.7K OHM 1% 1/10W 0603"       -> 88.7 kohm, tolerance 1 %, p_rated 0.1 W
    "Single P-Channel 30 V 4.1 mOhm 125 nC" -> v_ds 30 V, rds_on 4.1 mohm, qg 125 nC

Everything returned carries provenance ``bom_description``. Unknown tokens are ignored,
never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dfr.core.contracts import PartClass, Rating, RatingProvenance
from dfr.core.values import ParsedValue, parse_value

# number, optional separator, optional prefix, optional space, unit. Catches "50V", "4.2 A",
# "85-V", "1/10W", "86.35MOHM", "4.1 mOhm", "125 nC", "200MW", "3.3V", "88.7K OHM".
_TOKEN_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?(?:/\d+)?)\s*-?\s*"
    r"([pnu\u00b5\u03bcmkKMG]?) ?(F|H|OHM|OHMS|V|A|W|HZ|C)(?![A-Za-z])",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PACKAGE_RE = re.compile(
    r"(?<![\w-])(0201|0402|0603|0805|1206|1210|1812|2010|2512|SOD\w*|SOT\w*|TO-[\w-]+"
    r"|DFN\w*|WFDFN|QFN\w*|SON\w*)(?![\w-])",
    re.IGNORECASE,
)
_DIELECTRIC_RE = re.compile(r"(?<!\w)(X7R|X5R|X7S|X7T|X8R|C0G|NP0|Y5V|Z5U)(?!\w)", re.IGNORECASE)
_IC_VOUT_RE = re.compile(r"(?<![A-Za-z])Fixed\s+(\d+(?:\.\d+)?)\s*V(?![A-Za-z])", re.IGNORECASE)

# SI unit of a token -> rating name, per part class. "value" is the part's primary value.
_ROLE_BY_CLASS: dict[PartClass, dict[str, str]] = {
    PartClass.CAPACITOR: {"F": "value", "V": "v_rated"},
    PartClass.INDUCTOR: {"H": "value", "A": "i_rated", "ohm": "dcr"},
    PartClass.RESISTOR: {"ohm": "value", "W": "p_rated", "V": "v_rated"},
    PartClass.DIODE: {"V": "v_rated", "W": "p_rated", "A": "i_rated"},
    PartClass.TRANSISTOR: {"V": "v_ds", "ohm": "rds_on", "C": "qg", "A": "i_d"},
    PartClass.FUSE: {"A": "i_rated", "V": "v_rated"},
    PartClass.IC: {"A": "i_out"},  # IC voltages are ambiguous (vout? abs max?); see _IC_VOUT_RE
}


@dataclass
class DescriptionFacts:
    value: ParsedValue | None = None
    ratings: dict[str, Rating] = field(default_factory=dict)
    package: str | None = None
    dielectric: str | None = None
    tolerance_pct: float | None = None
    keywords: tuple[str, ...] = ()


def parse_description(text: str | None, part_class: PartClass) -> DescriptionFacts:
    facts = DescriptionFacts()
    if not text:
        return facts
    roles = _ROLE_BY_CLASS.get(part_class, {})
    for num, prefix, unit_text in _TOKEN_RE.findall(text):
        parsed = parse_value(f"{num}{prefix}{unit_text}")
        if parsed is None or not parsed.unit:
            continue
        role = roles.get(parsed.unit)
        if role is None:
            continue
        if role == "value":
            if facts.value is None:
                facts.value = parsed
        elif role not in facts.ratings:
            facts.ratings[role] = _rating(role, parsed.magnitude, parsed.unit, text)
    if part_class is PartClass.IC and (m := _IC_VOUT_RE.search(text)):
        facts.ratings["v_out"] = _rating("v_out", float(m.group(1)), "V", text)
    if m := _PERCENT_RE.search(text):
        facts.tolerance_pct = float(m.group(1))
    if m := _PACKAGE_RE.search(text):
        facts.package = m.group(1).upper()
    if m := _DIELECTRIC_RE.search(text):
        facts.dielectric = m.group(1).upper()
    facts.keywords = tuple(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]+", text))
    return facts


def _rating(name: str, value: float, unit: str, source: str) -> Rating:
    return Rating(
        name=name,
        value=value,
        unit=unit,
        provenance=RatingProvenance.BOM_DESCRIPTION,
        provenance_ref=source,
    )
