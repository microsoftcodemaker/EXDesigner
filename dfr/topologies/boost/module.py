"""Boost-family topology plugin: boost and inverting buck-boost (T26), one equation core."""

from __future__ import annotations

from dfr.api import API_VERSION, ModuleSpec
from dfr.topologies.boost.pattern import BOOST, BUCK_BOOST, PATTERN_VERSION, BoostFamilyPattern
from dfr.topologies.boost.template import BoostFamilyTemplate

PATTERNS = {k: BoostFamilyPattern(k) for k in (BOOST, BUCK_BOOST)}
TEMPLATES = {k: BoostFamilyTemplate(k) for k in (BOOST, BUCK_BOOST)}

MODULE = ModuleSpec(
    id="topology_boost",
    name="Boost and inverting buck-boost converters",
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
