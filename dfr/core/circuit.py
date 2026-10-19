"""Read-only connectivity index over a NetlistGraph, shared by every TopologyPattern.

Patterns ask structural questions ("which nets touch an inductor terminal and an IC pin?")
without touching pin names. Built once per match; cheap to query.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from dfr.core.contracts import NetKind, NetlistGraph, Part, PartClass, Pin


@dataclass
class CircuitIndex:
    parts: dict[str, Part]
    pins_by_refdes: dict[str, list[Pin]] = field(default_factory=dict)
    pins_by_net: dict[str, list[Pin]] = field(default_factory=dict)
    net_kind: dict[str, NetKind] = field(default_factory=dict)

    @classmethod
    def build(cls, graph: NetlistGraph, parts: Iterable[Part]) -> CircuitIndex:
        idx = cls(parts={p.refdes: p for p in parts})
        by_ref: dict[str, list[Pin]] = defaultdict(list)
        by_net: dict[str, list[Pin]] = defaultdict(list)
        for pin in graph.pins:
            if pin.refdes not in idx.parts:
                continue  # pruned (DNP) or undefined component
            by_ref[pin.refdes].append(pin)
            if pin.net_name is not None:
                by_net[pin.net_name].append(pin)
        idx.pins_by_refdes = dict(by_ref)
        idx.pins_by_net = dict(by_net)
        idx.net_kind = {n.name: n.kind for n in graph.nets}
        return idx

    # ----------------------------------------------------------------- queries
    def part(self, refdes: str) -> Part | None:
        return self.parts.get(refdes)

    def nets_of(self, refdes: str) -> list[str]:
        """Distinct nets a part touches, in pin order."""
        seen: list[str] = []
        for pin in self.pins_by_refdes.get(refdes, []):
            if pin.net_name and pin.net_name not in seen:
                seen.append(pin.net_name)
        return seen

    def pins_of_on(self, refdes: str, net: str) -> list[Pin]:
        return [p for p in self.pins_by_refdes.get(refdes, []) if p.net_name == net]

    def refdes_on(self, net: str, *classes: PartClass) -> list[str]:
        """Distinct parts on a net, optionally filtered by class."""
        out: list[str] = []
        for pin in self.pins_by_net.get(net, []):
            part = self.parts.get(pin.refdes)
            if part is None or pin.refdes in out:
                continue
            if not classes or part.part_class in classes:
                out.append(pin.refdes)
        return out

    def parts_of_class(self, *classes: PartClass) -> list[Part]:
        return [p for p in self.parts.values() if p.part_class in classes]

    def two_terminal_between(self, refdes: str) -> tuple[str, str] | None:
        """For a two-terminal part return (net_a, net_b); None if not exactly two distinct nets."""
        nets = self.nets_of(refdes)
        return (nets[0], nets[1]) if len(nets) == 2 else None

    def other_net(self, refdes: str, net: str) -> str | None:
        pair = self.two_terminal_between(refdes)
        if pair is None or net not in pair:
            return None
        return pair[1] if pair[0] == net else pair[0]

    def ground_nets(self) -> set[str]:
        return {n for n, k in self.net_kind.items() if k is NetKind.GROUND}

    def is_ground(self, net: str) -> bool:
        return self.net_kind.get(net) is NetKind.GROUND

    def pin_count(self, refdes: str) -> int:
        return len(self.pins_by_refdes.get(refdes, []))
