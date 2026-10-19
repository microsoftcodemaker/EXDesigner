"""Module/plugin registry: discovery, pipeline composition, and typed spec catalogs."""

from dfr.core.registry.catalog import (
    ReportSectionRegistry,
    ScreenRegistry,
    SpecRegistry,
    TopologyRegistry,
)
from dfr.core.registry.discovery import DiscoveryResult, discover, user_plugin_dir
from dfr.core.registry.pipeline import Pipeline, build_pipeline
from dfr.core.registry.spec import ModuleSpec, RunContext, ServiceNotFound, StepFn, StepResult

__all__ = [
    "DiscoveryResult",
    "ModuleSpec",
    "Pipeline",
    "ReportSectionRegistry",
    "RunContext",
    "ScreenRegistry",
    "ServiceNotFound",
    "SpecRegistry",
    "StepFn",
    "StepResult",
    "TopologyRegistry",
    "build_pipeline",
    "discover",
    "user_plugin_dir",
]
