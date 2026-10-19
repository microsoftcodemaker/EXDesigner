"""Stub module proving the registry contract (MOD-02, MOD-03, MOD-05).

It is discovered from its folder alone, owns one table through its own Alembic branch,
and contributes one pipeline step. CI deletes this folder and the suite must still pass.
Copy this folder to start a real module.
"""

from __future__ import annotations

from pathlib import Path

from dfr.api import API_VERSION, DiagnosticSink, ModuleSpec, RunContext, StepResult

MODULE_ID = "example"
VERSION = "0.1.0"


def run(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink(MODULE_ID)
    parts = ctx.get_or("parts", [])
    sink.info("EXAMPLE_RAN", f"example step saw {len(parts)} parts")
    return StepResult.from_sink(sink, example_marker=f"{MODULE_ID}@{VERSION}")


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Example module",
    version=VERSION,
    api_version=API_VERSION,
    requires=("parts",),
    provides=("example_marker",),
    optional=True,
    step=run,
    migrations_path=Path(__file__).parent / "migrations",
    table_prefix="example_",
)
