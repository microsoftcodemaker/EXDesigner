"""Buck pattern, integrated-switch and discrete variants (PRD 3.12).

Structural constraints only (connectivity, not pin names), so unknown IC pinouts do not
block candidate detection. Everything is a *proposal*; M12 requires user confirmation.

Integrated variant:
    sw   : net with >=1 IC pin and exactly one inductor terminal (+ optional boot cap,
           optional catch-diode cathode). The IC on sw is role ``ic``.
    vout : the inductor's other net (or through a sense resistor <= 100 mohm, verify).
    vin  : the net (other than sw/vout/ground) shared by IC pins and capacitors to ground.
    gnd  : ground net touched by the IC.
    output_cap / input_cap : capacitors between vout / vin and ground.
    boot_cap : capacitor from sw to another pin of the ic. feedback_divider: optional.

Discrete variant:
    sw   : net touching one inductor terminal, a FET terminal and a FET or diode terminal.
    high_side_switch : FET between vin and sw. low_side_switch : FET between sw and gnd
    (or catch_diode : diode between sw and gnd). controller : IC on FET gate nets or sw.

Confidence = 0.6 * topology constraints satisfied + 0.2 * rail-name agreement
             + 0.2 * pin-function source (library/user over inferred).  Weights: verify.
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

PATTERN_ID = "buck"
PATTERN_VERSION = "0.1.0"
VARIANT_INTEGRATED = "integrated"
VARIANT_DISCRETE = "discrete"
SENSE_RESISTOR_MAX_OHM = 0.1  # verify
RAIL_NAME_HINTS = {
    "vin": ("vin", "in", "bus", "vbat", "vbus"),
    "sw": ("sw", "lx", "phase", "switch"),
    "vout": ("vout", "out"),
    "gnd": ("gnd", "pgnd", "agnd", "0"),
}
W_TOPOLOGY, W_NAMES, W_PINS = 0.6, 0.2, 0.2  # verify


@dataclass
class _Candidate:
    variant: str
    sw: str
    inductor: str
    vout: str
    ic: str | None = None
    high_side: str | None = None
    low_side: str | None = None
    catch_diode: str | None = None
    controller: str | None = None
    sense_resistor: str | None = None
    vin: str | None = None
    gnd: str | None = None
    boot_cap: str | None = None
    output_caps: list[str] = field(default_factory=list)
    input_caps: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    evidence: list[ConstraintEvidence] = field(default_factory=list)

    def ok(self, constraint: str, text: str) -> None:
        self.evidence.append(
            ConstraintEvidence(constraint=constraint, satisfied=True, evidence=text)
        )

    def fail(self, constraint: str, text: str) -> None:
        self.evidence.append(
            ConstraintEvidence(constraint=constraint, satisfied=False, evidence=text)
        )


class BuckPattern(TopologyPattern):
    id = PATTERN_ID
    version = PATTERN_VERSION
    roles = (
        "ic",
        "inductor",
        "output_cap",
        "input_cap",
        "boot_cap",
        "feedback_divider",
        "high_side_switch",
        "low_side_switch",
        "catch_diode",
        "controller",
        "sense_resistor",
        "other",
    )
    rails = ("vin", "sw", "vout", "gnd")

    def __init__(self, variant: str = VARIANT_INTEGRATED) -> None:
        if variant not in (VARIANT_INTEGRATED, VARIANT_DISCRETE):
            msg = f"unknown buck variant {variant!r}"
            raise ValueError(msg)
        self.variant = variant

    # ------------------------------------------------------------------ match
    def match(self, graph: NetlistGraph, parts: Sequence[Part]) -> list[PatternMatch]:
        idx = CircuitIndex.build(graph, parts)
        candidates = [
            c for L in idx.parts_of_class(PartClass.INDUCTOR) for c in self._candidates_for(idx, L)
        ]
        matches = [self._to_match(idx, c) for c in candidates]
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches

    def _candidates_for(self, idx: CircuitIndex, inductor: Part) -> list[_Candidate]:
        pair = idx.two_terminal_between(inductor.refdes)
        if pair is None:
            return []
        out: list[_Candidate] = []
        for sw, other in (pair, pair[::-1]):
            if idx.is_ground(sw):
                continue
            cand = (
                self._integrated(idx, inductor, sw, other)
                if self.variant == VARIANT_INTEGRATED
                else self._discrete(idx, inductor, sw, other)
            )
            if cand is not None:
                out.append(cand)
        return out

    # ------------------------------------------------------------------ integrated
    def _integrated(self, idx: CircuitIndex, L: Part, sw: str, vout: str) -> _Candidate | None:
        ics = idx.refdes_on(sw, PartClass.IC)
        if not ics:
            return None  # no IC on this inductor terminal: not a candidate at all
        cand = _Candidate(VARIANT_INTEGRATED, sw=sw, inductor=L.refdes, vout=vout)
        if len(ics) == 1:
            cand.ic = ics[0]
            cand.ok("sw_has_one_ic", f"{sw}: IC {cand.ic} pins {_pins(idx, cand.ic, sw)}")
        else:
            cand.ic = ics[0]
            cand.fail(
                "sw_has_one_ic", f"{sw}: several ICs on sw ({', '.join(ics)}); picked {cand.ic}"
            )
        self._resolve_vout_and_sense(idx, cand)
        gnds = [n for n in idx.nets_of(cand.ic) if idx.is_ground(n)]
        if gnds:
            cand.gnd = gnds[0]
            cand.ok("ic_on_ground", f"{cand.ic} pins on {cand.gnd}")
        else:
            cand.fail("ic_on_ground", f"{cand.ic} touches no ground net")
        self._collect_caps(idx, cand)
        self._find_vin(idx, cand, supply_part=cand.ic)
        self._boot_cap(idx, cand)
        self._feedback(idx, cand, cand.ic)
        diodes = [
            d
            for d in idx.refdes_on(sw, PartClass.DIODE)
            if idx.other_net(d, sw) in idx.ground_nets()
        ]
        if diodes:
            cand.catch_diode = diodes[0]
            cand.ok("catch_diode", f"{diodes[0]} between {sw} and ground (asynchronous)")
        return cand

    # ------------------------------------------------------------------ discrete
    def _discrete(  # noqa: PLR0912 - one branch per structural constraint
        self, idx: CircuitIndex, L: Part, sw: str, vout: str
    ) -> _Candidate | None:
        fets = idx.refdes_on(sw, PartClass.TRANSISTOR)
        if not fets:
            return None
        cand = _Candidate(VARIANT_DISCRETE, sw=sw, inductor=L.refdes, vout=vout)
        self._resolve_vout_and_sense(idx, cand)
        gnds = idx.ground_nets()
        for fet in fets:
            others = [n for n in idx.nets_of(fet) if n != sw]
            if any(n in gnds for n in others):
                cand.low_side = cand.low_side or fet
            else:
                cand.high_side = cand.high_side or fet
        diodes = [d for d in idx.refdes_on(sw, PartClass.DIODE) if idx.other_net(d, sw) in gnds]
        if cand.high_side:
            cand.ok("high_side_switch", f"{cand.high_side} on {sw} and a non-ground net")
        else:
            cand.fail("high_side_switch", f"no FET on {sw} with a non-ground second power net")
        if cand.low_side:
            cand.ok("low_side_or_diode", f"{cand.low_side} between {sw} and ground")
        elif diodes:
            cand.catch_diode = diodes[0]
            cand.ok("low_side_or_diode", f"catch diode {diodes[0]} between {sw} and ground")
        else:
            cand.fail("low_side_or_diode", f"no low-side FET or catch diode on {sw}")
        if cand.high_side:
            power_nets = [n for n in idx.nets_of(cand.high_side) if n != sw and n not in gnds]
            cand.vin = _best_vin(idx, power_nets)
        cand.gnd = next(iter(gnds), None)
        self._collect_caps(idx, cand)
        if cand.vin:
            cand.ok("vin_found", f"vin = {cand.vin} via {cand.high_side}")
        else:
            cand.fail("vin_found", "could not identify vin from the high-side switch")
        gate_nets = {n for f in (cand.high_side, cand.low_side) if f for n in idx.nets_of(f)} - {
            sw,
            cand.vin,
            cand.gnd,
        }
        ics = {ic for n in gate_nets | {sw} for ic in idx.refdes_on(n, PartClass.IC)}
        if ics:
            cand.controller = sorted(ics)[0]
            cand.ok("controller", f"{cand.controller} on gate/sw nets")
        return cand

    # ------------------------------------------------------------------ shared helpers
    def _resolve_vout_and_sense(self, idx: CircuitIndex, cand: _Candidate) -> None:
        """Allow vout to sit behind a low-value sense resistor."""
        vout = cand.vout
        caps = [
            c
            for c in idx.refdes_on(vout, PartClass.CAPACITOR)
            if idx.other_net(c, vout) in idx.ground_nets()
        ]
        if caps:
            cand.ok(
                "inductor_to_vout",
                f"{cand.inductor}: {cand.sw} -> {vout} with {len(caps)} capacitor(s) to ground",
            )
            return
        for r in idx.refdes_on(vout, PartClass.RESISTOR):
            part = idx.part(r)
            beyond = idx.other_net(r, vout)
            if (
                part
                and part.value_si is not None
                and part.value_si <= SENSE_RESISTOR_MAX_OHM
                and beyond
            ):
                caps2 = [
                    c
                    for c in idx.refdes_on(beyond, PartClass.CAPACITOR)
                    if idx.other_net(c, beyond) in idx.ground_nets()
                ]
                if caps2:
                    cand.sense_resistor, cand.vout = r, beyond
                    cand.ok(
                        "inductor_to_vout",
                        f"{cand.inductor}: {cand.sw} -> {vout} -> {r} "
                        f"({part.value_si:g} ohm) -> {beyond}",
                    )
                    return
        cand.fail(
            "inductor_to_vout", f"{vout}: no capacitors to ground on the inductor's output net"
        )

    def _collect_caps(self, idx: CircuitIndex, cand: _Candidate) -> None:
        gnds = idx.ground_nets()
        cand.output_caps = [
            c
            for c in idx.refdes_on(cand.vout, PartClass.CAPACITOR)
            if idx.other_net(c, cand.vout) in gnds
        ]
        if cand.output_caps:
            cand.ok("output_caps", f"{', '.join(cand.output_caps)} between {cand.vout} and ground")
        else:
            cand.fail("output_caps", f"no capacitor between {cand.vout} and ground")
        if cand.vin and not cand.input_caps:
            cand.input_caps = [
                c
                for c in idx.refdes_on(cand.vin, PartClass.CAPACITOR)
                if idx.other_net(c, cand.vin) in gnds
            ]
            if cand.input_caps:
                cand.ok("input_caps", f"{', '.join(cand.input_caps)} between {cand.vin} and ground")

    def _find_vin(self, idx: CircuitIndex, cand: _Candidate, supply_part: str) -> None:
        gnds = idx.ground_nets()
        excluded = {cand.sw, cand.vout} | gnds
        options = [n for n in idx.nets_of(supply_part) if n not in excluded]
        scored: list[tuple[int, str, list[str]]] = []
        for net in options:
            caps = [
                c for c in idx.refdes_on(net, PartClass.CAPACITOR) if idx.other_net(c, net) in gnds
            ]
            if caps:
                scored.append((len(caps) * 10 + len(idx.pins_of_on(supply_part, net)), net, caps))
        if scored:
            scored.sort(reverse=True)
            _, cand.vin, cand.input_caps = scored[0]
            cand.ok(
                "vin_found",
                f"vin = {cand.vin}: {supply_part} pins {_pins(idx, supply_part, cand.vin)}, "
                f"caps {', '.join(cand.input_caps)}",
            )
        else:
            cand.fail(
                "vin_found", f"no net on {supply_part} carries capacitors to ground besides vout"
            )
        if cand.vin and cand.input_caps:
            cand.ok("input_caps", f"{', '.join(cand.input_caps)} between {cand.vin} and ground")

    def _boot_cap(self, idx: CircuitIndex, cand: _Candidate) -> None:
        if not cand.ic:
            return
        for c in idx.refdes_on(cand.sw, PartClass.CAPACITOR):
            other = idx.other_net(c, cand.sw)
            if other and not idx.is_ground(other) and cand.ic in idx.refdes_on(other):
                cand.boot_cap = c
                cand.ok(
                    "boot_cap",
                    f"{c} from {cand.sw} to {other} ({cand.ic} pin {_pins(idx, cand.ic, other)})",
                )
                return

    def _feedback(self, idx: CircuitIndex, cand: _Candidate, ic: str) -> None:
        gnds = idx.ground_nets()
        for r in idx.refdes_on(cand.vout, PartClass.RESISTOR):
            mid = idx.other_net(r, cand.vout)
            if not mid or ic not in idx.refdes_on(mid):
                continue
            lower = [
                r2
                for r2 in idx.refdes_on(mid, PartClass.RESISTOR)
                if r2 != r and idx.other_net(r2, mid) in gnds
            ]
            if lower:
                cand.feedback = [r, *lower]
                cand.ok(
                    "feedback_divider",
                    f"{r}/{lower[0]} divider from {cand.vout} to ground, midpoint on {ic}",
                )
                return

    # ------------------------------------------------------------------ scoring
    def _to_match(self, idx: CircuitIndex, cand: _Candidate) -> PatternMatch:
        sat = sum(e.satisfied for e in cand.evidence)
        topo = sat / len(cand.evidence) if cand.evidence else 0.0
        rails = {"sw": cand.sw, "vout": cand.vout}
        if cand.vin:
            rails["vin"] = cand.vin
        if cand.gnd:
            rails["gnd"] = cand.gnd
        names = sum(_name_agrees(rail, net) for rail, net in rails.items()) / 4
        pins = _pin_source_score(idx, [p for p in (cand.ic, cand.high_side, cand.low_side) if p])
        confidence = round(W_TOPOLOGY * topo + W_NAMES * names + W_PINS * pins, 3)

        roles: dict[str, tuple[str, ...]] = {"inductor": (cand.inductor,)}
        for role, value in (
            ("ic", cand.ic),
            ("high_side_switch", cand.high_side),
            ("low_side_switch", cand.low_side),
            ("catch_diode", cand.catch_diode),
            ("controller", cand.controller),
            ("sense_resistor", cand.sense_resistor),
            ("boot_cap", cand.boot_cap),
        ):
            if value:
                roles[role] = (value,)
        if cand.output_caps:
            roles["output_cap"] = tuple(cand.output_caps)
        if cand.input_caps:
            roles["input_cap"] = tuple(cand.input_caps)
        if cand.feedback:
            roles["feedback_divider"] = tuple(cand.feedback)
        return PatternMatch(
            pattern_id=f"{PATTERN_ID}_{cand.variant}"
            if cand.variant == VARIANT_INTEGRATED
            else PATTERN_ID,
            pattern_version=PATTERN_VERSION,
            confidence=min(1.0, confidence),
            rails=rails,
            roles=roles,
            evidence=list(cand.evidence),
            unmet=[e.constraint for e in cand.evidence if not e.satisfied],
        )

    # ------------------------------------------------------------------ propose
    def propose(self, match: PatternMatch, parts: Sequence[Part]) -> RoleProposal:
        ev = {e.constraint: e.evidence for e in match.evidence}
        assigned: dict[str, RoleAssignment] = {}
        rail_for_role = {
            "ic": "sw",
            "inductor": "sw",
            "output_cap": "vout",
            "input_cap": "vin",
            "boot_cap": "sw",
            "high_side_switch": "sw",
            "low_side_switch": "sw",
            "catch_diode": "sw",
            "sense_resistor": "vout",
            "feedback_divider": "vout",
            "controller": None,
        }
        for role, refs in match.roles.items():
            for ref in refs:
                rail = rail_for_role.get(role)
                assigned[ref] = RoleAssignment(
                    refdes=ref,
                    role=role,
                    rail=rail if rail in match.rails else None,
                    confidence=match.confidence,
                    evidence=_evidence_for(role, ref, ev),
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
            assignments=sorted(assigned.values(), key=lambda a: _refdes_key(a.refdes)),
        )


# ---------------------------------------------------------------------- small helpers


def _pins(idx: CircuitIndex, refdes: str, net: str) -> str:
    return ",".join(p.pin_id for p in idx.pins_of_on(refdes, net))


def _best_vin(idx: CircuitIndex, nets: list[str]) -> str | None:
    best: tuple[int, str] | None = None
    for n in nets:
        caps = [
            c
            for c in idx.refdes_on(n, PartClass.CAPACITOR)
            if idx.other_net(c, n) in idx.ground_nets()
        ]
        if best is None or len(caps) > best[0]:
            best = (len(caps), n)
    return best[1] if best else None


def _name_agrees(rail: str, net: str) -> bool:
    low = net.lower()
    return any(h in low for h in RAIL_NAME_HINTS.get(rail, ()))


def _pin_source_score(idx: CircuitIndex, refdes_list: list[str]) -> float:
    pins = [p for r in refdes_list for p in idx.pins_by_refdes.get(r, [])]
    if not pins:
        return 0.0
    good = sum(
        p.function_provenance
        in (PinFunctionProvenance.USER, PinFunctionProvenance.SEED, PinFunctionProvenance.NETLIST)
        for p in pins
    )
    return good / len(pins)


def _evidence_for(role: str, ref: str, ev: dict[str, str]) -> str:
    key = {
        "ic": "sw_has_one_ic",
        "inductor": "inductor_to_vout",
        "output_cap": "output_caps",
        "input_cap": "input_caps",
        "boot_cap": "boot_cap",
        "high_side_switch": "high_side_switch",
        "low_side_switch": "low_side_or_diode",
        "catch_diode": "low_side_or_diode",
        "controller": "controller",
        "sense_resistor": "inductor_to_vout",
        "feedback_divider": "feedback_divider",
    }.get(role, "")
    text = ev.get(key, role)
    return text if text.startswith(f"{ref}:") else f"{ref}: {text}"


def _refdes_key(refdes: str) -> tuple[str, int]:
    i = 0
    while i < len(refdes) and refdes[i].isalpha():
        i += 1
    digits = "".join(ch for ch in refdes[i:] if ch.isdigit())
    return (refdes[:i], int(digits) if digits else 0)
