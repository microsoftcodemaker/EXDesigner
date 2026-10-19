"""Persist an imported design (parts, nets, pins) into the core tables."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from dfr.core.contracts import Net, NetlistGraph, Part, Pin
from dfr.core.db.repos import DesignRepo, NetlistRepo, PartRepo
from dfr.core.ports import Clock


@dataclass(frozen=True)
class PersistedDesign:
    design_id: int
    design_version_id: int
    part_ids: dict[str, int]  # refdes -> part id
    net_ids: dict[str, int]  # net name -> net id


def persist_design(
    session: Session,
    clock: Clock,
    *,
    design_id: int,
    parts: list[Part],
    nets: list[Net],
    pins: list[Pin],
    graph: NetlistGraph,
    bom_hash: str | None,
    note: str | None = None,
) -> PersistedDesign:
    """Create a new design version and store everything. Versions are append-only."""
    designs = DesignRepo(session, clock)
    version = designs.new_version(
        design_id,
        bom_hash=bom_hash,
        netlist_hash=graph.source_hash,
        netlist_format=graph.source_format,
        note=note,
    )
    part_repo = PartRepo(session)
    net_repo = NetlistRepo(session)

    part_ids: dict[str, int] = {}
    for p in parts:
        stored_part = part_repo.add(version.id, p)
        if stored_part.id is not None:
            part_ids[p.refdes] = stored_part.id
    net_ids: dict[str, int] = {}
    for n in nets:
        stored_net = net_repo.add_net(version.id, n)
        if stored_net.id is not None:
            net_ids[n.name] = stored_net.id
    for pin in pins:
        part_id = part_ids.get(pin.refdes)
        if part_id is None:
            continue  # pins of undefined components were already reported by the parser
        net_repo.add_pin(part_id, pin, net_ids.get(pin.net_name) if pin.net_name else None)
    session.flush()
    return PersistedDesign(design_id, version.id, part_ids, net_ids)
