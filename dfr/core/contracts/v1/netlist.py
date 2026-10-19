"""Nets, pins, connectivity graph and join results (PRD section 3.1)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.contracts.v1.enums import AutoUserProvenance, NetKind, PinFunctionProvenance


class Net(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    name: str
    normalized_name: str
    kind: NetKind = NetKind.UNKNOWN
    kind_provenance: AutoUserProvenance = AutoUserProvenance.AUTO


class Pin(BaseModel):
    """One component pin. ``pin_id`` is the designator as written in the netlist ("7", "A1")."""

    model_config = ConfigDict(frozen=True)

    id: int | None = None
    refdes: str
    pin_id: str
    net_name: str | None = None
    function: str | None = None
    function_provenance: PinFunctionProvenance | None = None
    pintype: str | None = None


class NetlistComponent(BaseModel):
    """A component as the netlist describes it, before joining to the BOM."""

    model_config = ConfigDict(frozen=True)

    refdes: str
    footprint: str | None = None
    comment: str | None = None
    value: str | None = None


class NetlistGraph(BaseModel):
    """Plain data form of the connectivity graph. Modules build networkx graphs from it."""

    components: list[NetlistComponent] = Field(default_factory=list)
    nets: list[Net] = Field(default_factory=list)
    pins: list[Pin] = Field(default_factory=list)
    source_format: str | None = None
    source_hash: str | None = None

    def pins_on_net(self, net_name: str) -> list[Pin]:
        return [p for p in self.pins if p.net_name == net_name]

    def pins_of(self, refdes: str) -> list[Pin]:
        return [p for p in self.pins if p.refdes == refdes]


class NetlistImportResult(BaseModel):
    graph: NetlistGraph
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class JoinResult(BaseModel):
    """Netlist-to-BOM join. Keys are refdes."""

    matched: dict[str, int] = Field(default_factory=dict)  # refdes -> part id
    bom_only: list[str] = Field(default_factory=list)
    netlist_only: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class PinoutRequest(BaseModel):
    """Ask the user for a pinout the app cannot know (never guessed, PRD NET-06)."""

    model_config = ConfigDict(frozen=True)

    refdes: str
    mpn: str | None
    libref: str | None
    footprint: str | None
    pin_ids: tuple[str, ...]
    inferred: dict[str, str] = Field(default_factory=dict)  # pin_id -> inferred function
