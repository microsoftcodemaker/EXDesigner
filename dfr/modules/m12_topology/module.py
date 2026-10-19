"""M12: topology pattern match and role assignment. Services only; no pipeline step."""

from __future__ import annotations

from dfr.api import API_VERSION, ModuleSpec
from dfr.modules.m12_topology.service import (
    MODULE_ID,
    apply_edits,
    available_patterns,
    check_staleness,
    confirm_roles,
    match_topology,
    prefill_from_stale,
    role_map_for,
)

MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Topology match and role assignment",
    version="0.1.0",
    api_version=API_VERSION,
    requires=(),
    provides=(),
    optional=False,
    services={
        "available_patterns": available_patterns,
        "match_topology": match_topology,
        "apply_edits": apply_edits,
        "confirm_roles": confirm_roles,
        "role_map_for": role_map_for,
        "check_staleness": check_staleness,
        "prefill_from_stale": prefill_from_stale,
    },
)
