"""Netlist parser registry (NET-07). A new format is one file here plus one line in parsers()."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from dfr.core.contracts import NetlistImportResult


class NetlistParser(Protocol):
    id: str
    extensions: tuple[str, ...]

    def sniff(self, data: bytes, name: str) -> bool: ...

    def parse(self, data: bytes, name: str) -> NetlistImportResult: ...


def default_parsers() -> Sequence[NetlistParser]:
    from dfr.modules.m1_bom.netlist.protel import ProtelParser  # noqa: PLC0415 - avoid cycle

    parsers: list[NetlistParser] = [ProtelParser()]
    return parsers


def pick_parser(
    data: bytes, name: str, parsers: Sequence[NetlistParser], fmt: str | None = None
) -> NetlistParser | None:
    if fmt is not None:
        return next((p for p in parsers if p.id == fmt), None)
    for p in parsers:
        if p.sniff(data, name):
            return p
    lower = name.lower()
    return next((p for p in parsers if lower.endswith(p.extensions)), None)
