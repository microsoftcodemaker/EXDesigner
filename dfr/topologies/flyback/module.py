"""Flyback topology plugin (T27): pattern + CCM/DCM template; defaults in data/topologies."""

from __future__ import annotations

from dfr.api import API_VERSION, ModuleSpec
from dfr.topologies.flyback.pattern import PATTERN_ID, PATTERN_VERSION, FlybackPattern
from dfr.topologies.flyback.template import FlybackTemplate

PATTERNS = {PATTERN_ID: FlybackPattern()}
TEMPLATES = {PATTERN_ID: FlybackTemplate()}

MODULE = ModuleSpec(
    id="topology_flyback",
    name="Flyback converter (CCM / DCM)",
    version=PATTERN_VERSION,
    api_version=API_VERSION,
    requires=(),
    provides=(),
    optional=True,
    services={
        "topology.patterns": lambda: PATTERNS,
        "topology.templates": lambda: TEMPLATES,
    },
)
