"""Altium netlist, Protel text format (PRD 3.1, NET-02; decision 6).

Layout (from the supplied sample, CRLF):

    [                     (                 Component block: designator, footprint,
    R7                    Buck_in           comment (holds the MPN), then three blank
    RES0603R              C1-2              lines. Net block: name, then REF-PIN lines.
    CRCW060388K7FKEA      U3-1              A net may be empty. REF-PIN is split at the
    <blank x3>            )                 last hyphen (verify against more samples).
    ]

Pin numbers only; no pin names or types. Unparsed lines are reported with line numbers.
"""

from __future__ import annotations

import hashlib

from dfr.core.contracts import (
    Net,
    NetlistComponent,
    NetlistGraph,
    NetlistImportResult,
    Pin,
)
from dfr.core.diagnostics import DiagnosticSink

FORMAT_ID = "altium_protel"
_ENCODINGS = ("ascii", "latin-1")


class ProtelParser:
    id = FORMAT_ID
    extensions: tuple[str, ...] = (".net",)

    def sniff(self, data: bytes, name: str) -> bool:
        head = data.lstrip()[:2]
        return head.startswith(b"[") and b"\n]" in data[:4000]

    def parse(self, data: bytes, name: str) -> NetlistImportResult:
        sink = DiagnosticSink("m1_bom")
        lines = _decode(data).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        state = _ParseState()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            line_no = i + 1
            if line == "[":
                comp, i = _read_component(lines, i + 1, sink)
                state.add_component(comp, line_no, sink)
            elif line == "(":
                net, net_pins, i = _read_net(lines, i + 1, sink)
                state.add_net(net, net_pins, line_no, sink)
            else:
                if line:
                    sink.warning("NET_UNPARSED_LINE", f"unexpected text {line!r}", line_no=i + 1)
                i += 1

        for p in state.pins:
            if p.refdes not in state.seen_refdes:
                sink.warning(
                    "NET_PIN_UNKNOWN_COMPONENT",
                    f"net {p.net_name!r} references undefined component {p.refdes!r}",
                )
        if not state.components:
            sink.error("NET_NO_COMPONENTS", "no component blocks found")

        graph = NetlistGraph(
            components=state.components,
            nets=state.nets,
            pins=state.pins,
            source_format=FORMAT_ID,
            source_hash=hashlib.sha256(data).hexdigest(),
        )
        return NetlistImportResult(graph=graph, diagnostics=list(sink.items))


class _ParseState:
    def __init__(self) -> None:
        self.components: list[NetlistComponent] = []
        self.nets: list[Net] = []
        self.pins: list[Pin] = []
        self.seen_refdes: dict[str, int] = {}
        self.seen_nets: dict[str, int] = {}

    def add_component(
        self, comp: NetlistComponent | None, line_no: int, sink: DiagnosticSink
    ) -> None:
        if comp is None:
            return
        if comp.refdes in self.seen_refdes:
            sink.error(
                "NET_DUPLICATE_REFDES",
                f"component {comp.refdes!r} also defined near line {self.seen_refdes[comp.refdes]}",
                line_no=line_no,
            )
            return
        self.seen_refdes[comp.refdes] = line_no
        self.components.append(comp)

    def add_net(
        self, net: Net | None, net_pins: list[Pin], line_no: int, sink: DiagnosticSink
    ) -> None:
        if net is None:
            return
        if net.name in self.seen_nets:
            sink.error(
                "NET_DUPLICATE_NET",
                f"net {net.name!r} also defined near line {self.seen_nets[net.name]}",
                line_no=line_no,
            )
            return
        self.seen_nets[net.name] = line_no
        self.nets.append(net)
        self.pins.extend(net_pins)
        if not net_pins:
            sink.info("NET_EMPTY_NET", f"net {net.name!r} has no pins", line_no=line_no)


def _decode(data: bytes) -> str:
    for enc in _ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _read_component(
    lines: list[str], i: int, sink: DiagnosticSink
) -> tuple[NetlistComponent | None, int]:
    """Consume lines after '[' up to and including ']'. Returns (component, next index)."""
    start = i
    fields: list[str] = []
    while i < len(lines):
        line = lines[i].rstrip("\r")
        if line.strip() == "]":
            break
        fields.append(line.strip())
        i += 1
    else:
        sink.error("NET_UNTERMINATED_BLOCK", "component block without ']'", line_no=start)
        return None, i
    i += 1  # past ']'
    while fields and fields[-1] == "":
        fields.pop()
    if not fields or not fields[0]:
        sink.error("NET_COMPONENT_NO_REFDES", "component block without designator", line_no=start)
        return None, i
    refdes = fields[0]
    footprint = fields[1] if len(fields) > 1 and fields[1] else None
    comment = fields[2] if len(fields) > 2 and fields[2] else None
    return NetlistComponent(refdes=refdes, footprint=footprint, comment=comment), i


def _read_net(lines: list[str], i: int, sink: DiagnosticSink) -> tuple[Net | None, list[Pin], int]:
    """Consume lines after '(' up to and including ')'. Returns (net, pins, next index)."""
    start = i
    name: str | None = None
    pins: list[Pin] = []
    while i < len(lines):
        line = lines[i].strip()
        line_no = i + 1
        if line == ")":
            break
        if name is None:
            if line:
                name = line
        elif line:
            refdes, sep, pin_id = line.rpartition("-")
            if not sep or not refdes or not pin_id:
                sink.warning("NET_BAD_NODE", f"cannot split {line!r} into REF-PIN", line_no=line_no)
            else:
                pins.append(Pin(refdes=refdes, pin_id=pin_id, net_name=name))
        i += 1
    else:
        sink.error("NET_UNTERMINATED_BLOCK", "net block without ')'", line_no=start)
        return None, [], i
    i += 1
    if name is None:
        sink.error("NET_NET_NO_NAME", "net block without a name", line_no=start)
        return None, [], i
    return Net(name=name, normalized_name=name), pins, i
