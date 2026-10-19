"""Headless import -> match -> confirm workflow, driven entirely through registry services.

Used by the CLI and by end-to-end tests; the GUI screens call the same services one step at
a time. Nothing here imports a module package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from dfr.core.contracts import Diagnostic, PinoutRequest, RoleEdit, Stage
from dfr.core.db.repos import DesignRepo
from dfr.core.ports import Clock, FileSystem, LocalFileSystem
from dfr.core.registry import DiscoveryResult


@dataclass
class ImportOutcome:
    design_id: int
    design_version_id: int
    part_count: int
    net_count: int
    pinout_requests: list[PinoutRequest]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    _parts: list[Any] = field(default_factory=list, repr=False)
    _graph: Any = None
    _hints: dict[str, tuple[str, ...]] = field(default_factory=dict, repr=False)


def import_design(
    session: Session,
    registry: DiscoveryResult,
    clock: Clock,
    *,
    name: str,
    bom_path: Path,
    netlist_path: Path,
    topology: str,
    fs: FileSystem | None = None,
) -> ImportOutcome:
    fs = fs or LocalFileSystem()
    svc = registry.service
    imported, bom = svc("import_bom")(
        fs.read_bytes(bom_path), bom_path.name, session=session, clock=clock
    )
    net = svc("import_netlist")(fs.read_bytes(netlist_path), netlist_path.name)
    joined = svc("join_netlist")(net.graph, bom)
    pruned = svc("prune_dnp")(net.graph, joined.parts)
    pins = svc("resolve_pin_functions")(pruned, joined.parts)

    design = DesignRepo(session, clock).create(name, topology_template=topology)
    stored = svc("persist_design")(
        session,
        clock,
        design_id=design.id,
        parts=joined.parts,
        nets=net.graph.nets,
        pins=pins.pins,
        graph=net.graph,
        bom_hash=imported.source_hash,
    )
    parts_with_ids = [
        p.model_copy(update={"id": stored.part_ids.get(p.refdes)}) for p in joined.parts
    ]
    diags = [*imported.diagnostics, *bom.diagnostics, *net.diagnostics, *joined.diagnostics]
    return ImportOutcome(
        design.id,
        stored.design_version_id,
        len(joined.parts),
        len(net.graph.nets),
        pins.requests,
        diags,
        parts_with_ids,
        pruned,
        bom.topology_hints,
    )


def match_and_confirm(
    session: Session,
    registry: DiscoveryResult,
    clock: Clock,
    imported: ImportOutcome,
    *,
    topology: str,
    edits: list[RoleEdit] | None = None,
    auto_confirm: bool = False,
) -> tuple[Stage | None, list[Diagnostic]]:
    """Propose roles; persist and confirm only when the caller says so (REC-06)."""
    svc = registry.service
    patterns = svc("available_patterns")(registry.services_named("topology.patterns"))
    inference: dict[str, Any] = {}
    for provider in registry.services_named("topology.inference"):
        inference.update(provider())
    out = svc("match_topology")(
        imported._graph,
        imported._parts,
        topology,
        patterns,
        inference=inference,
        bom_hints=imported._hints,
    )
    if out.proposal is None or not auto_confirm:
        return None, out.diagnostics
    stage = svc("confirm_roles")(
        session,
        clock,
        design_version_id=imported.design_version_id,
        proposal=out.proposal,
        edits=edits or [],
        netlist_hash=imported._graph.source_hash,
    )
    return stage, out.diagnostics
