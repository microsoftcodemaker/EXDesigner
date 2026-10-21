"""Rebuild in-memory session state from stored rows (reopening a design from Home).

Two pieces the GUI needs after a restart: the import context Circuit Review matches against
(``ImportOutcome`` with the connectivity graph rebuilt from the net/pin tables), and a
``RunOutcome`` for a stored, frozen run (results loaded through each module's ``load_*``
service). Nothing here imports a module package.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from dfr.app.orchestrator import RunOutcome, plan_pipeline
from dfr.app.workflow import ImportOutcome
from dfr.core.contracts import NetlistComponent, NetlistGraph, Pin
from dfr.core.db.models import DesignVersion
from dfr.core.db.repos import DiagnosticRepo, NetlistRepo, PartRepo, RunRepo, StressRepo
from dfr.core.ports import Clock
from dfr.core.registry import DiscoveryResult, RunContext

# capability -> service that loads a stored run's rows for it (absent module: skipped)
RESULT_LOADERS: tuple[tuple[str, str], ...] = (
    ("derating", "load_derating_results"),
    ("thermal", "load_thermal_results"),
    ("lifetime", "load_lifetime_results"),
    ("failure_rate", "load_failure_rate_results"),
    ("refinement", "load_refinement_items"),
    ("fmea", "load_fmea_rows"),
)
# what ``run_tier1`` seeds besides the orchestrator's own capabilities
RUN_EXTRAS = ("converter_spec", "templates", "stage", "role_map", "ruleset", "mission_profile")


def load_import_context(
    session: Session, registry: DiscoveryResult, clock: Clock, design_version_id: int
) -> ImportOutcome | None:
    """The stored parts/nets/pins of a version as an ``ImportOutcome`` (graph DNP-pruned)."""
    version = session.get(DesignVersion, design_version_id)
    if version is None:
        return None
    parts = PartRepo(session).for_version(design_version_id)
    if not parts:
        return None
    nets = NetlistRepo(session)
    pins: list[Pin] = []
    for p in parts:
        if p.id is not None:
            pins.extend(nets.pins_for_part(p.id))
    graph = NetlistGraph(
        components=[
            NetlistComponent(refdes=p.refdes, footprint=p.package, comment=p.description)
            for p in parts
        ],
        nets=nets.nets_for_version(design_version_id),
        pins=pins,
        source_format=version.netlist_format,
        source_hash=version.netlist_hash,
    )
    svc = registry.service
    if registry.has_service("prune_dnp"):
        graph = svc("prune_dnp")(graph, parts)
    requests = (
        svc("resolve_pin_functions")(graph, parts, session=session, clock=clock).requests
        if registry.has_service("resolve_pin_functions")
        else []
    )
    return ImportOutcome(
        version.design_id,
        design_version_id,
        len(parts),
        len(graph.nets),
        list(requests),
        [],
        parts,
        graph,
        {},
    )


def load_run_outcome(
    session: Session, registry: DiscoveryResult, clock: Clock, run_id: int
) -> RunOutcome | None:
    """A frozen run as a ``RunOutcome``: stored results per capability, effective stress."""
    run = RunRepo(session, clock).get(run_id)
    if run is None:
        return None
    by_id = {v.id: v for v in StressRepo(session, clock).for_version(run.design_version_id) if v.id}
    effective = {
        key: by_id[i]
        for key, i in RunRepo(session, clock).effective_ids(run_id).items()
        if i in by_id
    }
    data: dict[str, Any] = {
        "run": run,
        "config": run.config,
        "clock": clock,
        "parts": PartRepo(session).for_version(run.design_version_id),
        "effective_stress": effective,
        "stress": list(effective.values()),
        "prompts": StressRepo(session, clock).open_prompts(run.design_version_id),
    }
    if run.config.mission_profile is not None:
        data["mission_profile"] = run.config.mission_profile
    for capability, service in RESULT_LOADERS:
        if registry.has_service(service):
            data[capability] = list(registry.service(service)(session, run_id))
    pipeline = plan_pipeline(registry.modules, run.config, extra_capabilities=RUN_EXTRAS)
    return RunOutcome(run, pipeline, RunContext(data), DiagnosticRepo(session).for_run(run_id))
