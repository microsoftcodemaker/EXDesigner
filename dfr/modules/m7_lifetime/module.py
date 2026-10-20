"""M7: lifetime models (PRD 3.7). Owns ``m7_lifetime_result`` (branch ``m7_lifetime``).

Step inputs: parts, effective_stress; optional thermal (M6), converter_spec (Ta),
mission_profile (defaults when absent, stated in every result's assumptions).
Output: ``lifetime`` = list[LifetimeResult], one per (part, applicable model).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from dfr.api import API_VERSION, DiagnosticSink, ModuleSpec, RunContext, StepResult
from dfr.core.contracts import (
    Confidence,
    LifetimeResult,
    MissionProfile,
    Part,
    StressKey,
    StressValue,
    ThermalResult,
)
from dfr.core.db.base import Base
from dfr.core.extension import LifetimeModel
from dfr.modules.m7_lifetime.constants import (
    MODULE_ID,
    LifetimeConstants,
    load_constants,
    load_constants_file,
)
from dfr.modules.m7_lifetime.models import LifetimeContext, default_models

VERSION = "0.1.0"


class LifetimeResultRow(Base):
    __tablename__ = "m7_lifetime_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mechanism: Mapped[str] = mapped_column(String(40), nullable=False)
    model_id: Mapped[str] = mapped_column(String(60), nullable=False)
    life_hours: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    input_stress_ids: Mapped[str] = mapped_column(String(200), nullable=False, default="")


def estimate_lifetimes(
    parts: list[Part],
    effective: Mapping[StressKey, StressValue],
    constants: LifetimeConstants,
    *,
    thermal: list[ThermalResult] | None = None,
    profile: MissionProfile | None = None,
    t_ambient: float = 25.0,
    models: list[LifetimeModel] | None = None,
    sink: DiagnosticSink | None = None,
) -> list[LifetimeResult]:
    sink = sink if sink is not None else DiagnosticSink(MODULE_ID)
    profile = profile or MissionProfile()
    ctx = LifetimeContext(constants, profile, t_ambient)
    models = models if models is not None else default_models(constants)
    worst_tj: dict[int, ThermalResult] = {}
    for t in thermal or []:
        if t.part_id not in worst_tj or t.tj > worst_tj[t.part_id].tj:
            worst_tj[t.part_id] = t
    results: list[LifetimeResult] = []
    for part in parts:
        if part.id is None or part.dnp:
            continue
        stress = [v for k, v in effective.items() if k.part_id == part.id]
        for model in models:
            if not model.applies_to(part):
                continue
            try:
                r = model.estimate(part, stress, worst_tj.get(part.id), ctx)
            except Exception as exc:  # a bad datum must not stop the run (never raise on parts)
                sink.error(
                    "LIFETIME_MODEL_FAILED",
                    f"{part.refdes}: {model.id} raised {exc!r}; skipped",
                    part_id=part.id,
                )
                continue
            if r.life_hours is None:
                sink.info(
                    "LIFETIME_NOT_AVAILABLE",
                    f"{part.refdes}: {model.id}: {r.assumptions[0] if r.assumptions else 'n/a'}",
                    part_id=part.id,
                )
            elif r.life_hours < profile.target_life_hours:
                sink.warning(
                    "LIFETIME_BELOW_TARGET",
                    f"{part.refdes}: {r.mechanism} {r.life_hours / 8766:.1f} y < target "
                    f"{profile.target_life_years:g} y ({r.confidence.value} confidence)",
                    part_id=part.id,
                )
            results.append(r)
    return results


def run(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink(MODULE_ID)
    constants = ctx.get_or("lifetime_constants") or load_constants()
    if constants is None:
        sink.error("LIFETIME_NO_CONSTANTS", "constants 'default' not found; lifetime skipped")
        return StepResult.from_sink(sink, lifetime=[])
    sink.extend(constants.diagnostics)
    if constants.version == 0:
        return StepResult.from_sink(sink, lifetime=[])
    spec = ctx.get_or("converter_spec")
    profile: MissionProfile = ctx.get_or("mission_profile") or MissionProfile()
    results = estimate_lifetimes(
        ctx.get("parts"),
        ctx.get("effective_stress"),
        constants,
        thermal=ctx.get_or("thermal"),
        profile=profile,
        t_ambient=spec.t_ambient if spec is not None else 25.0,
        sink=sink,
    )
    sink.info(
        "LIFETIME_SUMMARY",
        f"{sum(r.life_hours is not None for r in results)} estimate(s), "
        f"{sum(r.life_hours is None for r in results)} not available; "
        f"profile: target {profile.target_life_years:g} y, "
        f"{profile.on_off_cycles_per_year:g} on/off cycles per year",
    )
    return StepResult.from_sink(sink, lifetime=results, mission_profile=profile)


def persist(session: Session, run_id: int, result: StepResult) -> dict[str, Any] | None:
    rows: list[LifetimeResult] = result.outputs.get("lifetime", [])
    for r in rows:
        session.add(
            LifetimeResultRow(
                run_id=run_id,
                part_id=r.part_id,
                mechanism=r.mechanism,
                model_id=r.model_id,
                life_hours=r.life_hours,
                confidence=r.confidence.value,
                assumptions_json=json.dumps(list(r.assumptions)),
                input_stress_ids=",".join(str(i) for i in r.input_stress_ids),
            )
        )
    session.flush()
    return None


def load_results(session: Session, run_id: int) -> list[LifetimeResult]:
    rows = session.scalars(
        select(LifetimeResultRow)
        .where(LifetimeResultRow.run_id == run_id)
        .order_by(LifetimeResultRow.id)
    )
    return [
        LifetimeResult(
            part_id=r.part_id,
            mechanism=r.mechanism,
            model_id=r.model_id,
            life_hours=r.life_hours,
            confidence=Confidence(r.confidence),
            assumptions=tuple(json.loads(r.assumptions_json)),
            input_stress_ids=tuple(int(i) for i in r.input_stress_ids.split(",") if i),
        )
        for r in rows
    ]


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Lifetime models",
    version=VERSION,
    api_version=API_VERSION,
    requires=("parts", "effective_stress"),
    optional_requires=("thermal", "converter_spec", "mission_profile", "stress"),
    provides=("lifetime",),
    optional=True,
    step=run,
    persist=persist,
    services={
        "estimate_lifetimes": estimate_lifetimes,
        "load_lifetime_constants": load_constants,
        "load_lifetime_constants_file": load_constants_file,
        "load_lifetime_results": load_results,
    },
    migrations_path=Path(__file__).parent / "migrations",
    table_prefix="m7_",
)
