"""Two-stage part classification with confidence (PRD 3.1, BOM-04).

Stage 1: reference-designator prefix (R, C, L, D, Q, U, J, F, SW, Y, TP, T).
Stage 2: keyword rules on value, description, footprint and LibRef for class (when no refdes)
and subtype. Confidence below ``REVIEW_THRESHOLD`` puts the part in the manual-review queue.
Keywords such as "buck"/"step-down" are hints for M12 only, never decisive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dfr.core.contracts import PartClass, RawPart

REVIEW_THRESHOLD = 0.7

_PREFIX_CLASS: dict[str, PartClass] = {
    "R": PartClass.RESISTOR,
    "RN": PartClass.RESISTOR,
    "RV": PartClass.RESISTOR,
    "C": PartClass.CAPACITOR,
    "L": PartClass.INDUCTOR,
    "FB": PartClass.INDUCTOR,
    "D": PartClass.DIODE,
    "LED": PartClass.DIODE,
    "Z": PartClass.DIODE,
    "Q": PartClass.TRANSISTOR,
    "M": PartClass.TRANSISTOR,
    "U": PartClass.IC,
    "IC": PartClass.IC,
    "J": PartClass.CONNECTOR,
    "P": PartClass.CONNECTOR,
    "CN": PartClass.CONNECTOR,
    "X": PartClass.CONNECTOR,
    "F": PartClass.FUSE,
    "SW": PartClass.SWITCH,
    "S": PartClass.SWITCH,
    "Y": PartClass.CRYSTAL,
    "XTAL": PartClass.CRYSTAL,
    "TP": PartClass.TEST_POINT,
    "T": PartClass.TRANSFORMER,
    "TR": PartClass.TRANSFORMER,
    "MH": PartClass.OTHER,
    "H": PartClass.OTHER,
}

# Class keywords used when there is no refdes (BomDoc) or to confirm/contradict the prefix.
_CLASS_KEYWORDS: list[tuple[re.Pattern[str], PartClass]] = [
    (re.compile(r"\b(cap|capacitor|mlcc|elec|electrolytic|tantalum)\b", re.I), PartClass.CAPACITOR),
    (
        re.compile(r"\b(res|resistor|shunt|potentiometer|thermistor|ntc|ptc)\b", re.I),
        PartClass.RESISTOR,
    ),
    (re.compile(r"\b(ind|inductor|choke|ferrite|bead)\b", re.I), PartClass.INDUCTOR),
    (
        re.compile(r"\b(mosfet|nmos|pmos|n-?channel|p-?channel|transistor|bjt|igbt|fet)\b", re.I),
        PartClass.TRANSISTOR,
    ),
    (re.compile(r"\b(diode|schottky|zener|tvs|led|rectifier)\b", re.I), PartClass.DIODE),
    (re.compile(r"\b(fuse|polyfuse|ptc fuse)\b", re.I), PartClass.FUSE),
    (
        re.compile(r"\b(connector|header|terminal block|socket|jack|plug|receptacle)\b", re.I),
        PartClass.CONNECTOR,
    ),
    (re.compile(r"\b(crystal|oscillator|resonator)\b", re.I), PartClass.CRYSTAL),
    (re.compile(r"\b(transformer|xfmr)\b", re.I), PartClass.TRANSFORMER),
    (re.compile(r"\b(switch|pushbutton|tactile)\b", re.I), PartClass.SWITCH),
    (
        re.compile(
            r"\b(ic|regulator|monitor|controller|driver|amplifier|op-?amp|mcu|microcontroller|interface|converter|sensor)\b",
            re.I,
        ),
        PartClass.IC,
    ),
]

_SUBTYPE_KEYWORDS: dict[PartClass, list[tuple[re.Pattern[str], str]]] = {
    PartClass.CAPACITOR: [
        (re.compile(r"polymer", re.I), "polymer"),
        (re.compile(r"electrolytic|elec\b|CP_Radial|alum", re.I), "aluminum_electrolytic"),
        (re.compile(r"tantalum|\bta\b", re.I), "tantalum"),
        (re.compile(r"film|pet|pp\b", re.I), "film"),
        (re.compile(r"X7R|X5R|X7S|X8R|C0G|NP0|Y5V|MLCC|\bcer\b|ceramic", re.I), "ceramic"),
    ],
    PartClass.RESISTOR: [
        (re.compile(r"shunt|current sense|sense", re.I), "sense"),
        (re.compile(r"thermistor|ntc|ptc", re.I), "thermistor"),
        (re.compile(r"potentiometer|trimmer|pot\b", re.I), "potentiometer"),
        (re.compile(r"\bres\b|resistor|\bsmd\b|chip", re.I), "chip"),
    ],
    PartClass.INDUCTOR: [
        (re.compile(r"ferrite|bead|\bfb\b", re.I), "bead"),
        (re.compile(r"coupled", re.I), "coupled"),
        (re.compile(r"shielded|power|fixed ind|inductor|choke", re.I), "power"),
    ],
    PartClass.DIODE: [
        (re.compile(r"schottky|1N58|\bSS\d", re.I), "schottky"),
        (re.compile(r"zener|BZX", re.I), "zener"),
        (re.compile(r"\btvs\b|ESD|transient", re.I), "tvs"),
        (re.compile(r"\bled\b", re.I), "led"),
        (re.compile(r"rectifier|1N400|fast", re.I), "rectifier"),
    ],
    PartClass.TRANSISTOR: [
        (re.compile(r"p-?channel|pmos|\bpch\b", re.I), "mosfet_p"),
        (re.compile(r"n-?channel|nmos|\bnch\b", re.I), "mosfet_n"),
        (re.compile(r"mosfet|\bfet\b", re.I), "mosfet"),
        (re.compile(r"igbt", re.I), "igbt"),
        (re.compile(r"\bbjt\b|npn|pnp", re.I), "bjt"),
    ],
    PartClass.IC: [
        (
            re.compile(r"buck|step-?down|switching regulator|dc-?dc|dc/dc", re.I),
            "switching_regulator",
        ),
        (re.compile(r"\bldo\b|linear regulator", re.I), "ldo"),
        (re.compile(r"gate driver|driver", re.I), "gate_driver"),
        (re.compile(r"monitor|current sense|power monitor", re.I), "monitor"),
        (re.compile(r"mcu|microcontroller", re.I), "mcu"),
        (re.compile(r"op-?amp|amplifier", re.I), "opamp"),
    ],
    PartClass.CONNECTOR: [
        (re.compile(r"terminal block|screw", re.I), "terminal_block"),
        (re.compile(r"header|pin", re.I), "header"),
    ],
}

# Topology hints for M12 (never decisive, PRD 3.12 evidence layer 4).
_TOPOLOGY_HINTS = re.compile(r"\b(buck|step-?down|boost|step-?up|buck-?boost|flyback|ldo)\b", re.I)


@dataclass(frozen=True)
class Classification:
    part_class: PartClass
    subtype: str | None
    confidence: float
    topology_hints: tuple[str, ...] = ()
    conflict: str | None = None  # populated when prefix and keywords disagree


def classify(raw: RawPart) -> Classification:
    text = " ".join(filter(None, (raw.value, raw.description, raw.footprint, raw.libref, raw.mpn)))
    prefix_class = _class_from_refdes(raw.refdes)
    keyword_class = _class_from_keywords(text)

    conflict = None
    if prefix_class is not None and keyword_class is not None and prefix_class != keyword_class:
        # Prefix is the designer's intent; keywords are secondary. Flag for review.
        part_class, confidence = prefix_class, 0.5
        conflict = f"refdes prefix says {prefix_class.value}, text says {keyword_class.value}"
    elif prefix_class is not None:
        part_class = prefix_class
        confidence = 0.9 if keyword_class == prefix_class else 0.75
    elif keyword_class is not None:
        part_class, confidence = keyword_class, 0.7
    else:
        return Classification(PartClass.UNKNOWN, None, 0.0)

    subtype = _subtype(part_class, text)
    if subtype is not None:
        confidence = min(1.0, confidence + 0.1)
    hints = tuple(sorted({h.lower() for h in _TOPOLOGY_HINTS.findall(text)}))
    return Classification(part_class, subtype, round(confidence, 2), hints, conflict)


def _class_from_refdes(refdes: str | None) -> PartClass | None:
    if not refdes:
        return None
    m = re.match(r"^([A-Za-z]+)", refdes.strip())
    if not m:
        return None
    letters = m.group(1).upper()
    for n in range(len(letters), 0, -1):  # longest prefix first: "LED" before "L"
        if letters[:n] in _PREFIX_CLASS:
            return _PREFIX_CLASS[letters[:n]]
    return None


def _class_from_keywords(text: str) -> PartClass | None:
    for pattern, cls in _CLASS_KEYWORDS:
        if pattern.search(text):
            return cls
    return None


def _subtype(part_class: PartClass, text: str) -> str | None:
    for pattern, subtype in _SUBTYPE_KEYWORDS.get(part_class, []):
        if pattern.search(text):
            return subtype
    return None
