"""Flyback pattern (PRD 3.12, T27). Structural constraints only.

transformer    : a TRANSFORMER part (or a coupled inductor with >= 3 distinct nets).
sw             : a transformer net carrying the primary switch: a FET with a pin on ground or on a
                 net that reaches ground through a sense resistor <= 1 ohm (``primary_switch``,
                 ``sense_resistor``), or an IC with a ground pin (``ic``, integrated switch).
vin            : another non-ground transformer net with capacitors to ground (``input_cap``).
vout           : a net reached from a remaining (secondary) transformer net through a diode
                 (``output_diode``) and carrying capacitors to ground (``output_cap``).
clamp          : diodes from sw to a non-ground net other than vout (RCD / TVS clamp).

Confidence = 0.6 * constraints satisfied + 0.2 * rail-name agreement + 0.2 * pin-function
source (verify).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from dfr.core.circuit import CircuitIndex
from dfr.core.contracts import (
    ConstraintEvidence,
    NetlistGraph,
    Part,
    PartClass,
    PatternMatch,
    PinFunctionProvenance,
    Rail,
    RoleAssignment,
    RoleProposal,
)
from dfr.core.extension import TopologyPattern

PATTERN_ID = "flyback"
PATTERN_VERSION = "0.1.0"
SENSE_RESISTOR_MAX_OHM = 1.0  # verify
W_TOPOLOGY, W_NAMES, W_PINS = 0.6, 0.2, 0.2  # verify
RAIL_NAME_HINTS = {
    "vin": ("vin", "in", "bus", "hv", "bulk"),
    "sw": ("sw", "drain", "dr", "lx"),
    "vout": ("vout", "out", "sec"),
    "gnd": ("gnd", "0", "rtn", "com"),
}
RAIL_FOR_ROLE = {
    "transformer": "sw",
    "primary_switch": "sw",
    "ic": "sw",
    "sense_resistor": "sw",
    "clamp": "sw",
    "input_cap": "vin",
    "output_diode": "vout",
    "output_cap": "vout",
    "controller": None,
}


@dataclass
class _Cand:
    transformer: str
    sw: str
    vin: str | None = None
    vout: str | None = None
    gnd: str | None = None
    roles: dict[str, list[str]] = field(default_factory=dict)
    evidence: list[ConstraintEvidence] = field(default_factory=list)

    def check(self, constraint: str, ok: bool, text: str) -> None:
        self.evidence.append(ConstraintEvidence(constraint=constraint, satisfied=ok, evidence=text))

    def put(self, role: str, *refs: str) -> None:
        lst = self.roles.setdefault(role, [])
        lst.extend(r for r in refs if r not in lst)


class FlybackPattern(TopologyPattern):
    id = PATTERN_ID
    version = PATTERN_VERSION
    rails = ("vin", "sw", "vout", "gnd")
    roles = (
        "transformer",
        "primary_switch",
        "ic",
        "sense_resistor",
        "clamp",
        "output_diode",
        "output_cap",
        "input_cap",
        "controller",
        "other",
    )

    def match(self, graph: NetlistGraph, parts: Sequence[Part]) -> list[PatternMatch]:
        idx = CircuitIndex.build(graph, parts)
        xfmrs = [
            p
            for p in idx.parts_of_class(PartClass.TRANSFORMER, PartClass.INDUCTOR)
            if len(idx.nets_of(p.refdes)) >= 3
        ]
        out = [
            self._to_match(idx, c)
            for t in xfmrs
            for sw in idx.nets_of(t.refdes)
            if (c := self._candidate(idx, t.refdes, sw)) is not None
        ]
        out.sort(key=lambda m: m.confidence, reverse=True)
        return out

    def _candidate(self, idx: CircuitIndex, t: str, sw: str) -> _Cand | None:
        gnds = idx.ground_nets()
        if sw in gnds:
            return None
        cand = _Cand(transformer=t, sw=sw, gnd=next(iter(sorted(gnds)), None))
        if not self._switch(idx, cand, gnds):
            return None
        cand.put("transformer", t)
        t_nets = idx.nets_of(t)
        vins = sorted(
            ((len(_caps_to_ground(idx, n)), n) for n in t_nets if n != sw and n not in gnds),
            reverse=True,
        )
        if vins and vins[0][0] > 0:
            cand.vin = vins[0][1]
            cand.put("input_cap", *_caps_to_ground(idx, cand.vin))
            cand.check("primary_from_vin", True, f"{t}: {cand.vin} -> {sw}, input caps present")
        else:
            cand.check("primary_from_vin", False, f"{t}: no other winding net with caps to ground")
        secondary = [n for n in t_nets if n not in (sw, cand.vin)]
        for net in secondary:
            for d in idx.refdes_on(net, PartClass.DIODE):
                other = idx.other_net(d, net)
                if other and other not in t_nets and _caps_to_ground(idx, other):
                    cand.vout = other
                    cand.put("output_diode", d)
                    cand.put("output_cap", *_caps_to_ground(idx, other))
                    cand.check(
                        "secondary_rectifier", True, f"{d}: {net} -> {other}, caps on {other}"
                    )
                    break
            if cand.vout:
                break
        if cand.vout is None:
            cand.check(
                "secondary_rectifier", False, "no diode from a secondary net to a held output"
            )
        for d in idx.refdes_on(sw, PartClass.DIODE):
            other = idx.other_net(d, sw)
            if other and other not in gnds and other != cand.vout:
                cand.put("clamp", d)
        rails = {sw, cand.vin, cand.vout, *gnds}
        gates = {n for f in cand.roles.get("primary_switch", []) for n in idx.nets_of(f)} - rails
        ics = sorted({ic for n in gates for ic in idx.refdes_on(n, PartClass.IC)})
        if ics:
            cand.put("controller", ics[0])
        return cand

    def _switch(self, idx: CircuitIndex, cand: _Cand, gnds: set[str]) -> bool:
        for fet in idx.refdes_on(cand.sw, PartClass.TRANSISTOR):
            others = [n for n in idx.nets_of(fet) if n != cand.sw]
            if any(n in gnds for n in others):
                cand.put("primary_switch", fet)
                cand.check("primary_switch", True, f"{fet} between {cand.sw} and ground")
                return True
            for n in others:
                for r in idx.refdes_on(n, PartClass.RESISTOR):
                    part = idx.part(r)
                    small = (
                        part
                        and part.value_si is not None
                        and part.value_si <= SENSE_RESISTOR_MAX_OHM
                    )
                    if small and idx.other_net(r, n) in gnds:
                        cand.put("primary_switch", fet)
                        cand.put("sense_resistor", r)
                        cand.check("primary_switch", True, f"{fet} on {cand.sw}, source via {r}")
                        return True
        for ic in idx.refdes_on(cand.sw, PartClass.IC):
            if any(n in gnds for n in idx.nets_of(ic)):
                cand.put("ic", ic)
                cand.check("primary_switch", True, f"integrated switch {ic} on {cand.sw}")
                return True
        return False

    def _to_match(self, idx: CircuitIndex, cand: _Cand) -> PatternMatch:
        topo = sum(e.satisfied for e in cand.evidence) / len(cand.evidence)
        rails = {
            k: v
            for k, v in (("vin", cand.vin), ("sw", cand.sw), ("vout", cand.vout), ("gnd", cand.gnd))
            if v
        }
        names = sum(any(h in n.lower() for h in RAIL_NAME_HINTS[r]) for r, n in rails.items()) / 4
        active = cand.roles.get("primary_switch", []) + cand.roles.get("ic", [])
        pins = [p for r in active for p in idx.pins_by_refdes.get(r, [])]
        good = (
            PinFunctionProvenance.USER,
            PinFunctionProvenance.SEED,
            PinFunctionProvenance.NETLIST,
        )
        pin_score = sum(p.function_provenance in good for p in pins) / len(pins) if pins else 0.0
        conf = round(W_TOPOLOGY * topo + W_NAMES * names + W_PINS * pin_score, 3)
        return PatternMatch(
            pattern_id=PATTERN_ID,
            pattern_version=PATTERN_VERSION,
            confidence=min(1.0, conf),
            rails=rails,
            roles={k: tuple(v) for k, v in cand.roles.items()},
            evidence=list(cand.evidence),
            unmet=[e.constraint for e in cand.evidence if not e.satisfied],
        )

    def propose(self, match: PatternMatch, parts: Sequence[Part]) -> RoleProposal:
        assigned: dict[str, RoleAssignment] = {}
        for role, refs in match.roles.items():
            rail = RAIL_FOR_ROLE.get(role)
            for ref in refs:
                assigned[ref] = RoleAssignment(
                    refdes=ref,
                    role=role,
                    rail=rail if rail in match.rails else None,
                    confidence=match.confidence,
                    evidence=f"{ref}: {role} of the flyback stage",
                )
        for p in parts:
            if p.refdes not in assigned and not p.dnp:
                assigned[p.refdes] = RoleAssignment(
                    refdes=p.refdes,
                    role="other",
                    confidence=1.0,
                    evidence="not part of the matched stage; manual entry only",
                )
        return RoleProposal(
            pattern_id=match.pattern_id,
            pattern_version=match.pattern_version,
            confidence=match.confidence,
            rails=[Rail(rail=r, net_name=n) for r, n in match.rails.items()],
            assignments=sorted(assigned.values(), key=lambda a: a.refdes),
        )


def _caps_to_ground(idx: CircuitIndex, net: str) -> list[str]:
    gnds = idx.ground_nets()
    return [c for c in idx.refdes_on(net, PartClass.CAPACITOR) if idx.other_net(c, net) in gnds]
