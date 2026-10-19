"""BOM reader registry. A new format is one file in this folder plus one line in READERS."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from dfr.core.contracts import BomImportResult


class BomReader(Protocol):
    id: str
    extensions: tuple[str, ...]

    def sniff(self, data: bytes, name: str) -> bool:
        """True if this reader recognises the bytes (content beats extension)."""

    def read(self, data: bytes, name: str) -> BomImportResult: ...


def default_readers() -> Sequence[BomReader]:
    from dfr.modules.m1_bom.readers.bomdoc import BomDocReader  # noqa: PLC0415 - avoid import cycle

    readers: list[BomReader] = [BomDocReader()]
    return readers


def pick_reader(
    data: bytes, name: str, readers: Sequence[BomReader], fmt: str | None = None
) -> BomReader | None:
    if fmt is not None:
        return next((r for r in readers if r.id == fmt), None)
    for r in readers:
        if r.sniff(data, name):
            return r
    lower = name.lower()
    return next((r for r in readers if lower.endswith(r.extensions)), None)
