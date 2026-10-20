"""Public plugin API. Third-party modules and topologies import only from here."""

from dfr.core.contracts import API_VERSION
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.extension import (
    ChartSpec,
    FailureRateModel,
    LifetimeModel,
    ReportSectionSpec,
    ScreenSpec,
    TopologyPattern,
    TopologyTemplate,
)
from dfr.core.registry.spec import ModuleSpec, RunContext, ServiceNotFound, StepResult
from dfr.core.report import SOURCE_LABELS, muted, num, table

__all__ = [
    "API_VERSION",
    "SOURCE_LABELS",
    "ChartSpec",
    "DiagnosticSink",
    "FailureRateModel",
    "LifetimeModel",
    "ModuleSpec",
    "ReportSectionSpec",
    "RunContext",
    "ScreenSpec",
    "ServiceNotFound",
    "StepResult",
    "TopologyPattern",
    "TopologyTemplate",
    "muted",
    "num",
    "table",
]
