"""M2: operating-condition manager. Pipeline step + services.

Step inputs (context): parts, role_map, converter_spec, templates (pattern_id -> template),
stage (for pattern_id), clock; optional inferred_overrides, part_params.
Step outputs: stress (Tier 1 StressValues), prompts, inferred_values, template_params.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from dfr.api import API_VERSION, DiagnosticSink, ModuleSpec, RunContext, StepResult
from dfr.core.contracts import InferredValues, Stage, StressValue, ValuePrompt
from dfr.core.db.repos import StressRepo
from dfr.modules.m2_conditions.infer import MODULE_ID, infer_passives
from dfr.modules.m2_conditions.service import answer_prompt, compute_template_stress, manual_stress

VERSION = "0.1.0"


def run(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink(MODULE_ID)
    stage: Stage | None = ctx.get_or("stage")
    templates: Mapping[str, Any] = ctx.get_or("templates", {})
    spec = ctx.get_or("converter_spec")
    roles = ctx.get_or("role_map")
    if stage is None or roles is None:
        sink.error(
            "M2_NO_CONFIRMED_STAGE", "Tier 1 needs confirmed roles; confirm the circuit first"
        )
        return StepResult.from_sink(
            sink, stress=[], prompts=[], inferred_values=InferredValues(), template_params={}
        )
    if spec is None:
        sink.error(
            "M2_NO_SPEC", "converter spec missing (Vin min/max, Vout, Iout max, fsw, ambient)"
        )
        return StepResult.from_sink(
            sink, stress=[], prompts=[], inferred_values=InferredValues(), template_params={}
        )
    template = templates.get(stage.pattern_id)
    if template is None:
        sink.error(
            "M2_NO_TEMPLATE", f"no template for pattern {stage.pattern_id!r}; manual entry only"
        )
        inferred = infer_passives(ctx.get("parts"), roles, sink=sink)
        return StepResult.from_sink(
            sink, stress=[], prompts=[], inferred_values=inferred, template_params={}
        )

    result = compute_template_stress(
        template,
        spec,
        ctx.get("parts"),
        roles,
        ctx.get("clock"),
        overrides=ctx.get_or("inferred_overrides"),
        part_params=ctx.get_or("part_params"),
    )
    sink.extend(result.diagnostics)
    return StepResult.from_sink(
        sink,
        stress=result.stress,
        prompts=result.prompts,
        inferred_values=result.inferred,
        template_params=result.params,
    )


def persist(session: Session, run_id: int, result: StepResult) -> dict[str, Any]:
    """Store Tier 1 stress rows and open prompts; return stored rows (with ids)."""
    del run_id  # stress values attach to parts and versions, not to a run
    from dfr.core.ports import SystemClock  # noqa: PLC0415

    repo = StressRepo(session, SystemClock())
    stress: list[StressValue] = result.outputs.get("stress", [])
    prompts: list[ValuePrompt] = result.outputs.get("prompts", [])
    stored = repo.add_many(stress)
    version_id = _version_of(session, stress)
    stored_prompts = [repo.add_prompt(version_id, p) for p in prompts] if version_id else prompts
    return {"stress": stored, "prompts": stored_prompts}


def _version_of(session: Session, stress: list[StressValue]) -> int | None:
    from dfr.core.db.models import PartRow  # noqa: PLC0415

    for v in stress:
        row = session.get(PartRow, v.part_id)
        if row is not None:
            return int(row.design_version_id)
    return None


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Operating conditions and Tier 1 stress",
    version=VERSION,
    api_version=API_VERSION,
    requires=("parts", "role_map", "converter_spec", "templates", "stage"),
    provides=("stress", "prompts", "inferred_values", "template_params"),
    optional=False,
    step=run,
    persist=persist,
    services={
        "infer_passives": infer_passives,
        "compute_template_stress": compute_template_stress,
        "answer_prompt": answer_prompt,
        "manual_stress": manual_stress,
    },
)
