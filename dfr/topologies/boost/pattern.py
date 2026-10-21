"""Boost and inverting buck-boost patterns (PRD 3.12, T26). Structural constraints only.

Boost       : inductor vin -> sw; switch sw -> ground (FET ``low_side_switch`` or IC ``ic``);
              rectifier sw -> vout (diode ``catch_diode`` or FET ``high_side_switch``);
              capacitors vin -> ground (``input_cap``) and vout -> ground (``output_cap``).
Buck-boost  : (inverting) switch vin -> sw (FET ``high_side_switch`` or IC ``ic``); inductor
              sw -> ground; rectifier between sw and vout (diode ``catch_diode`` or FET
              ``low_side_switch``); vout is neither vin nor ground and carries capacitors.

Confidence = 0.6 * constraints satisfied + 0.2 * rail-name agreement + 0.2 * pin-function
source (same weights as the buck pattern; verify).
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

PATTERN_VERSION = "0.1.0"
BOOST, BUCK_BOOST = "boost", "buck_boost"
W_TOPOLOGY, W_NAMES, W_PINS = 0.6, 0.2, 0.2  # verify
RAIL_NAME_HINTS = {
    "vin": ("vin", "in", "bat", "bus"),
    "sw": ("sw", "lx", "phase", "switch"),
    "vout": ("vout", "out", "neg", "vee", "hv"),
    "gnd": ("gnd", "0", "rtn", "com"),
}
RAIL_FOR_ROLE = {
    "ic": "sw",
    "inductor": "sw",
    "low_side_switch": "sw",
    "high_side_switch": "sw",
    "catch_diode": "vout",
    "output_cap": "vout",
    "input_cap": "vin",
    "controller": None,
}


@dataclass
class _Cand:
    sw: str
    inductor: str
    vin: str | None = None
    vout: str | None = None
    gnd: str | None = None
    roles: dict[str, list[str]] = field(default_factory=dict)
    evidence: list[ConstraintEvidence] = field(default_factory=list)

    def check(self, constraint: str, ok: bool, text: str) -> None:
        self.evidence.append(ConstraintEvidence(constraint=constraint, satisfied=ok, evidence=text))

    def put(self, role: str, *refs: str) -> None:
        if refs:
            self.roles.setdefault(role, []).extend(r for r in refs if r not in self.roles[role])


class BoostFamilyPattern(TopologyPattern):
    version = PATTERN_VERSION
    rails = ("vin", "sw", "vout", "gnd")
    roles = (
        "ic",
        "inductor",
        "low_side_switch",
        "high_side_switch",
        "catch_diode",
        "output_cap",
        "input_cap",
        "controller",
        "other",
    )

    def __init__(self, kind: str) -> None:
        if kind not in (BOOST, BUCK_BOOST):
            msg = f"unknown boost-family pattern {kind!r}"
            raise ValueError(msg)
        self.id = kind

    # ------------------------------------------------------------------ match
    def match(self, graph: NetlistGraph, parts: Sequence[Part]) -> list[PatternMatch]:
        idx = CircuitIndex.build(graph, parts)
        out: list[PatternMatch] = []
        for ind in idx.parts_of_class(PartClass.INDUCTOR):
            pair = idx.two_terminal_between(ind.refdes)
            if pair is None:
                continue
            for a, b in (pair, pair[::-1]):
                cand = (
                    self._boost(idx, ind.refdes, vin=a, sw=b)
                    if self.id == BOOST
                    else self._buck_boost(idx, ind.refdes, gnd=a, sw=b)
                )
                if cand is not None:
                    out.append(self._to_match(idx, cand))
        out.sort(key=lambda m: m.confidence, reverse=True)
        return out

    def _boost(self, idx: CircuitIndex, ind: str, *, vin: str, sw: str) -> _Cand | None:
        gnds = idx.ground_nets()
        if sw in gnds or vin in gnds:
            return None
        switch = _switch_to(idx, sw, gnds)
        ic = None if switch else _ic_on(idx, sw, gnds)
        if switch is None and ic is None:
            return None
        cand = _Cand(sw=sw, inductor=ind, vin=vin, gnd=next(iter(sorted(gnds)), None))
        cand.put("inductor", ind)
        if switch:
            cand.put("low_side_switch", switch)
            cand.check("switch_to_ground", True, f"{switch} between {sw} and ground")
        else:
            assert ic is not None
            cand.put("ic", ic)
            cand.check("switch_to_ground", True, f"IC {ic} on {sw} with a ground pin")
        self._rectifier(idx, cand, exclude={vin, *gnds}, sync_role="high_side_switch")
        self._caps(idx, cand)
        self._controller(idx, cand)
        return cand

    def _buck_boost(self, idx: CircuitIndex, ind: str, *, gnd: str, sw: str) -> _Cand | None:
        gnds = idx.ground_nets()
        if gnd not in gnds or sw in gnds:
            return None
        cand = _Cand(sw=sw, inductor=ind, gnd=gnd)
        cand.put("inductor", ind)
        for fet in idx.refdes_on(sw, PartClass.TRANSISTOR):
            supplies = [n for n in idx.nets_of(fet) if n != sw and n not in gnds]
            vin = _with_caps(idx, supplies)
            if vin is not None:
                cand.vin = vin
                cand.put("high_side_switch", fet)
                break
        if cand.vin is None:
            for ic in idx.refdes_on(sw, PartClass.IC):
                vin = _with_caps(idx, [n for n in idx.nets_of(ic) if n != sw and n not in gnds])
                if vin is not None:
                    cand.vin = vin
                    cand.put("ic", ic)
                    break
        if cand.vin is None:
            return None
        switch = (cand.roles.get("high_side_switch") or cand.roles.get("ic") or ["?"])[0]
        cand.check("switch_from_vin", True, f"{switch} between {cand.vin} and {sw}")
        cand.check("inductor_to_ground", True, f"{ind} between {sw} and {gnd}")
        self._rectifier(idx, cand, exclude={cand.vin, *gnds}, sync_role="low_side_switch")
        self._caps(idx, cand)
        self._controller(idx, cand)
        return cand

    # ------------------------------------------------------------------ shared
    def _rectifier(
        self, idx: CircuitIndex, cand: _Cand, *, exclude: set[str], sync_role: str
    ) -> None:
        taken = {r for refs in cand.roles.values() for r in refs}
        for d in idx.refdes_on(cand.sw, PartClass.DIODE):
            other = idx.other_net(d, cand.sw)
            if other and other not in exclude and _caps_to_ground(idx, other):
                cand.vout = other
                cand.put("catch_diode", d)
                cand.check("rectifier", True, f"diode {d} between {cand.sw} and {other}")
                return
        for fet in idx.refdes_on(cand.sw, PartClass.TRANSISTOR):
            if fet in taken:
                continue
            outs = [n for n in idx.nets_of(fet) if n != cand.sw and n not in exclude]
            vout = _with_caps(idx, outs)
            if vout is not None:
                cand.vout = vout
                cand.put(sync_role, fet)
                cand.check("rectifier", True, f"synchronous FET {fet} between {cand.sw} and {vout}")
                return
        cand.check("rectifier", False, f"no diode or FET from {cand.sw} to a capacitor-held net")

    def _caps(self, idx: CircuitIndex, cand: _Cand) -> None:
        for role, net in (("input_cap", cand.vin), ("output_cap", cand.vout)):
            caps = _caps_to_ground(idx, net) if net else []
            cand.put(role, *caps)
            cand.check(
                role,
                bool(caps),
                f"{', '.join(caps)} between {net} and ground" if caps else f"none on {net}",
            )

    def _controller(self, idx: CircuitIndex, cand: _Cand) -> None:
        if "ic" in cand.roles:
            return
        rails = {cand.sw, cand.vin, cand.vout, *idx.ground_nets()}
        fets = cand.roles.get("low_side_switch", []) + cand.roles.get("high_side_switch", [])
        gates = {n for f in fets for n in idx.nets_of(f)} - rails
        ics = sorted({ic for n in gates for ic in idx.refdes_on(n, PartClass.IC)})
        if ics:
            cand.put("controller", ics[0])

    def _to_match(self, idx: CircuitIndex, cand: _Cand) -> PatternMatch:
        topo = sum(e.satisfied for e in cand.evidence) / len(cand.evidence)
        rails = {
            k: v
            for k, v in (("vin", cand.vin), ("sw", cand.sw), ("vout", cand.vout), ("gnd", cand.gnd))
            if v
        }
        names = sum(_name_agrees(r, n) for r, n in rails.items()) / 4
        active = [
            r
            for role in ("ic", "low_side_switch", "high_side_switch")
            for r in cand.roles.get(role, [])
        ]
        conf = round(W_TOPOLOGY * topo + W_NAMES * names + W_PINS * _pin_score(idx, active), 3)
        return PatternMatch(
            pattern_id=self.id,
            pattern_version=PATTERN_VERSION,
            confidence=min(1.0, conf),
            rails=rails,
            roles={k: tuple(v) for k, v in cand.roles.items()},
            evidence=list(cand.evidence),
            unmet=[e.constraint for e in cand.evidence if not e.satisfied],
        )

    # ------------------------------------------------------------------ propose
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
                    evidence=f"{ref}: {role} of the {self.id} stage",
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


# ---------------------------------------------------------------------- helpers


def _caps_to_ground(idx: CircuitIndex, net: str) -> list[str]:
    gnds = idx.ground_nets()
    return [c for c in idx.refdes_on(net, PartClass.CAPACITOR) if idx.other_net(c, net) in gnds]


def _with_caps(idx: CircuitIndex, nets: list[str]) -> str | None:
    scored = sorted(((len(_caps_to_ground(idx, n)), n) for n in nets), reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else None


def _switch_to(idx: CircuitIndex, sw: str, gnds: set[str]) -> str | None:
    for fet in idx.refdes_on(sw, PartClass.TRANSISTOR):
        if any(n in gnds for n in idx.nets_of(fet)):
            return fet
    return None


def _ic_on(idx: CircuitIndex, sw: str, gnds: set[str]) -> str | None:
    for ic in idx.refdes_on(sw, PartClass.IC):
        if any(n in gnds for n in idx.nets_of(ic)):
            return ic
    return None


def _name_agrees(rail: str, net: str) -> bool:
    low = net.lower()
    return any(h in low for h in RAIL_NAME_HINTS.get(rail, ()))


def _pin_score(idx: CircuitIndex, refs: list[str]) -> float:
    pins = [p for r in refs for p in idx.pins_by_refdes.get(r, [])]
    good = (PinFunctionProvenance.USER, PinFunctionProvenance.SEED, PinFunctionProvenance.NETLIST)
    return sum(p.function_provenance in good for p in pins) / len(pins) if pins else 0.0
