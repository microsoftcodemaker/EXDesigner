"""Netlist import service: bytes -> NetlistGraph with normalised, classified nets."""

from __future__ import annotations

from collections.abc import Sequence

from dfr.core.contracts import NetlistImportResult
from dfr.core.diagnostics import DiagnosticSink
from dfr.modules.m1_bom.netlist import NetlistParser, default_parsers, pick_parser
from dfr.modules.m1_bom.nets import annotate_nets


def import_netlist(
    data: bytes,
    name: str,
    *,
    fmt: str | None = None,
    parsers: Sequence[NetlistParser] | None = None,
) -> NetlistImportResult:
    parsers = parsers or default_parsers()
    parser = pick_parser(data, name, parsers, fmt)
    if parser is None:
        sink = DiagnosticSink("m1_bom")
        sink.error("NET_UNKNOWN_FORMAT", f"no netlist parser recognises {name!r}")
        from dfr.core.contracts import NetlistGraph  # noqa: PLC0415

        return NetlistImportResult(graph=NetlistGraph(), diagnostics=list(sink.items))
    result = parser.parse(data, name)
    graph = result.graph.model_copy(update={"nets": annotate_nets(result.graph.nets)})
    return NetlistImportResult(graph=graph, diagnostics=result.diagnostics)
