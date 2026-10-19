"""Net-name normalisation and power/ground/signal classification (PRD 3.1, NET-04).

Rules are deliberately simple and name-based; the user can override per net on the
Circuit Review screen (``kind_provenance = user``).
"""

from __future__ import annotations

import re

from dfr.core.contracts import Net, NetKind

# Auto-generated names from Altium ("NetC3_1") and KiCad ("Net-(C1-Pad1)").
_AUTO_RE = re.compile(r"^(Net-\(.+\)|Net[A-Z]+\d+_\d+|N\$\d+|unnamed_\d+)$", re.IGNORECASE)
_GROUND_RE = re.compile(
    r"^(A?GND\w*|P?GND\w*|D?GND\w*|0|GROUND|VSS\w*|COM|RTN|RETURN)$", re.IGNORECASE
)
_POWER_RE = re.compile(
    r"^(V(IN|CC|DD|BUS|BAT|SYS|OUT|REG|REF)\w*|[+-]?\d+(\.\d+)?V\d*\w*|\+\w+|VCC\w*|"
    r"\w*_IN|\w*_OUT|\w*_VIN|\w*_VOUT|\w*BUCK\w*|\w*RAIL\w*|\w*_PWR|PWR\w*|\w*_SUPPLY)$",
    re.IGNORECASE,
)


def normalize_net_name(name: str) -> str:
    """Strip hierarchy prefixes and surrounding whitespace: ``/sheet1/VIN`` -> ``VIN``."""
    text = name.strip()
    if "/" in text and not text.startswith("Net-("):
        text = text.rsplit("/", 1)[-1]
    return text


def is_auto_generated(name: str) -> bool:
    return bool(_AUTO_RE.match(name.strip()))


def classify_net(normalized: str) -> NetKind:
    if is_auto_generated(normalized):
        return NetKind.SIGNAL
    if _GROUND_RE.match(normalized):
        return NetKind.GROUND
    if _POWER_RE.match(normalized):
        return NetKind.POWER
    return NetKind.SIGNAL


def annotate_nets(nets: list[Net]) -> list[Net]:
    """Return copies with ``normalized_name`` and auto ``kind`` filled in."""
    out: list[Net] = []
    for net in nets:
        norm = normalize_net_name(net.name)
        out.append(net.model_copy(update={"normalized_name": norm, "kind": classify_net(norm)}))
    return out
