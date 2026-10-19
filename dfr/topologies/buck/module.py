"""Buck topology plugin: two pattern variants sharing one equation core (template in T12)."""

from __future__ import annotations

from dfr.api import API_VERSION, ModuleSpec
from dfr.topologies.buck.inference import infer_pin_functions
from dfr.topologies.buck.pattern import (
    PATTERN_VERSION,
    VARIANT_DISCRETE,
    VARIANT_INTEGRATED,
    BuckPattern,
)

PATTERNS = {
    "buck": BuckPattern(VARIANT_DISCRETE),
    "buck_integrated": BuckPattern(VARIANT_INTEGRATED),
}
INFERENCE = {"buck": infer_pin_functions, "buck_integrated": infer_pin_functions}

MODULE = ModuleSpec(
    id="topology_buck",
    name="Buck converter (discrete and integrated-switch)",
    version=PATTERN_VERSION,
    api_version=API_VERSION,
    requires=(),
    provides=(),
    optional=True,
    services={
        "topology.patterns": lambda: PATTERNS,
        "topology.inference": lambda: INFERENCE,
    },
)
