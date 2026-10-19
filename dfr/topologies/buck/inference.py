"""Pin-function inference for the buck pattern (PRD 3.12, prefill only).

Inferred functions are returned as ``refdes -> pin_id -> function`` and marked ``inferred``
by M1's pin resolver; they are never used until the user confirms them (NET-06).

Integrated buck: sw = ic pins on the inductor net; boot = pin joined to sw through a
capacitor; vin = ic pins on the net with the input capacitors; vout_sense = pin on vout;
gnd = pins on ground nets; fb = pin on a divider midpoint; others 'other'.
FETs: gate = the pin whose net carries no power connection; drain/source from the power
net each sits on (channel type from the part attributes, default N).
"""

from __future__ import annotations

from dfr.core.circuit import CircuitIndex
from dfr.core.contracts import NetlistGraph, Part, PatternMatch


def infer_pin_functions(
    match: PatternMatch, graph: NetlistGraph, parts: list[Part]
) -> dict[str, dict[str, str]]:
    idx = CircuitIndex.build(graph, parts)
    out: dict[str, dict[str, str]] = {}
    sw, vin, vout = (match.rails.get(k) for k in ("sw", "vin", "vout"))
    gnds = idx.ground_nets()

    for ic in match.roles.get("ic", ()):
        boot_net = _boot_net(idx, match, sw)
        fb_net = _fb_net(idx, match, ic)
        funcs: dict[str, str] = {}
        for pin in idx.pins_by_refdes.get(ic, []):
            net = pin.net_name
            if net == sw:
                funcs[pin.pin_id] = "sw"
            elif net is not None and net == boot_net:
                funcs[pin.pin_id] = "boot"
            elif net == vin:
                funcs[pin.pin_id] = "vin"
            elif net == vout:
                funcs[pin.pin_id] = "vout_sense"
            elif net in gnds:
                funcs[pin.pin_id] = "gnd"
            elif net is not None and net == fb_net:
                funcs[pin.pin_id] = "fb"
            else:
                funcs[pin.pin_id] = "other"
        out[ic] = funcs

    power_nets = {n for n in (sw, vin, vout) if n} | gnds
    for role in ("high_side_switch", "low_side_switch"):
        for fet in match.roles.get(role, ()):
            out[fet] = _infer_fet(idx, fet, role, power_nets, sw)

    for diode in match.roles.get("catch_diode", ()):
        out[diode] = {
            p.pin_id: "cathode" if p.net_name == sw else "anode"
            for p in idx.pins_by_refdes.get(diode, [])
        }
    return out


def _boot_net(idx: CircuitIndex, match: PatternMatch, sw: str | None) -> str | None:
    for cap in match.roles.get("boot_cap", ()):
        if sw:
            return idx.other_net(cap, sw)
    return None


def _fb_net(idx: CircuitIndex, match: PatternMatch, ic: str) -> str | None:
    divider = match.roles.get("feedback_divider", ())
    if not divider:
        return None
    for net in idx.nets_of(divider[0]):
        on_net = idx.refdes_on(net)
        if ic in on_net and all(r in on_net for r in divider[:2]):
            return net
    return None


def _infer_fet(
    idx: CircuitIndex, fet: str, role: str, power_nets: set[str], sw: str | None
) -> dict[str, str]:
    part = idx.part(fet)
    channel = (part.attributes.get("channel") if part else None) or "n"
    funcs: dict[str, str] = {}
    for p in idx.pins_by_refdes.get(fet, []):
        net = p.net_name or ""
        if net not in power_nets:
            funcs[p.pin_id] = "gate"
        elif role == "low_side_switch":
            funcs[p.pin_id] = "source" if idx.is_ground(net) else "drain"  # N-channel low side
        elif channel == "p":
            funcs[p.pin_id] = "drain" if net == sw else "source"  # P-channel high side
        else:
            funcs[p.pin_id] = "source" if net == sw else "drain"  # N-channel high side
    return funcs


__all__ = ["infer_pin_functions"]
