"""M3: risk triage. Owns ``m3_refinement_item`` and ``m3_waiver`` (branch ``m3_triage``).

Step inputs: parts, derating, effective_stress; optional thermal, stage (topology id),
role_map, prompts (M2's new prompts, for de-duplication) and ``triage_context`` (waivers and
open prompts, loaded by the ``run_context`` service before the run). Output: ``refinement``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from dfr.api import API_VERSION, DiagnosticSink, ModuleSpec, RunContext, StepResult
from dfr.core.contracts import RefinementItem, Stage, ValuePrompt
from dfr.core.db.base import Base
from dfr.core.db.models import PartRow
from dfr.core.db.repos import StressRepo
from dfr.core.db.types import UtcDateTime
from dfr.core.ports import Clock, SystemClock
from dfr.modules.m3_triage.config import MODULE_ID, load_config, load_config_file
from dfr.modules.m3_triage.engine import Waiver, triage

VERSION = "0.1.0"


class RefinementItemRow(Base):
    __tablename__ = "m3_refinement_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    flags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    params_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    scenarios_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    waiver_reason: Mapped[str | None] = mapped_column(Text)


class WaiverRow(Base):
    __tablename__ = "m3_waiver"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_version_id: Mapped[int] = mapped_column(
        ForeignKey("design_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flag: Mapped[str] = mapped_column(String(60), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


# ----------------------------------------------------------------------------- step


def run(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink(MODULE_ID)
    cfg = ctx.get_or("triage_config") or load_config()
    if cfg is None:
        sink.error("TRIAGE_NO_CONFIG", "triage config 'default' not found; triage skipped")
        return StepResult.from_sink(sink, refinement=[])
    sink.extend(cfg.diagnostics)
    if cfg.version == 0:
        return StepResult.from_sink(sink, refinement=[])
    stage: Stage | None = ctx.get_or("stage")
    extra: dict[str, Any] = ctx.get_or("triage_context") or {}
    items = triage(
        ctx.get("parts"),
        ctx.get("derating"),
        cfg,
        effective=ctx.get_or("effective_stress"),
        thermal=ctx.get_or("thermal"),
        lifetime=ctx.get_or("lifetime"),
        profile=ctx.get_or("mission_profile"),
        topology=stage.pattern_id if stage is not None else None,
        roles=ctx.get_or("role_map"),
        existing_prompts=[*ctx.get_or("prompts", []), *extra.get("open_prompts", [])],
        waivers=extra.get("waivers", []),
        sink=sink,
    )
    return StepResult.from_sink(sink, refinement=items)


def persist(session: Session, run_id: int, result: StepResult) -> dict[str, Any] | None:
    items: list[RefinementItem] = result.outputs.get("refinement", [])
    repo = StressRepo(session, SystemClock())
    stored: list[RefinementItem] = []
    for it in items:
        row = RefinementItemRow(
            run_id=run_id,
            part_id=it.part_id,
            score=it.score,
            status=it.status,
            flags_json=json.dumps(it.flags),
            reasons_json=json.dumps(it.reasons),
            params_json=json.dumps(it.parameters_to_refine),
            scenarios_json=json.dumps(it.recommended_scenarios),
            waiver_reason=it.waiver_reason,
        )
        session.add(row)
        session.flush()
        version_id = _version_of(session, it.part_id)
        prompts = [repo.add_prompt(version_id, p) for p in it.prompts] if version_id else it.prompts
        stored.append(it.model_copy(update={"id": row.id, "prompts": prompts}))
    return {"refinement": stored}


def _version_of(session: Session, part_id: int) -> int | None:
    row = session.get(PartRow, part_id)
    return int(row.design_version_id) if row is not None else None


# ----------------------------------------------------------------------------- services


def load_results(session: Session, run_id: int) -> list[RefinementItem]:
    """Stored refinement items for a run, best score first (prompts are in value_prompt)."""
    rows = session.scalars(
        select(RefinementItemRow)
        .where(RefinementItemRow.run_id == run_id)
        .order_by(RefinementItemRow.score.desc(), RefinementItemRow.id)
    )
    items = [
        RefinementItem(
            id=r.id,
            part_id=r.part_id,
            flags=json.loads(r.flags_json),
            reasons=json.loads(r.reasons_json),
            score=r.score,
            parameters_to_refine=json.loads(r.params_json),
            recommended_scenarios=json.loads(r.scenarios_json),
            status=r.status,
            waiver_reason=r.waiver_reason,
        )
        for r in rows
    ]
    return sorted(items, key=lambda i: (i.status != "open", -i.score, i.part_id))


def load_waivers(session: Session, design_version_id: int) -> list[Waiver]:
    rows = session.scalars(
        select(WaiverRow).where(WaiverRow.design_version_id == design_version_id)
    )
    return [Waiver(r.part_id, r.flag, r.reason) for r in rows]


def waive(  # noqa: PLR0917
    session: Session, clock: Clock, design_version_id: int, part_id: int, flag: str, reason: str
) -> Waiver:
    """Record a waiver (TRI-03). Takes effect on the next run; shown with its reason."""
    if not reason.strip():
        msg = "a waiver needs a reason"
        raise ValueError(msg)
    existing = session.scalars(
        select(WaiverRow).where(
            WaiverRow.design_version_id == design_version_id,
            WaiverRow.part_id == part_id,
            WaiverRow.flag == flag,
        )
    ).first()
    if existing is not None:
        existing.reason = reason
    else:
        session.add(
            WaiverRow(
                design_version_id=design_version_id,
                part_id=part_id,
                flag=flag,
                reason=reason,
                created_at=clock.now(),
            )
        )
    session.flush()
    return Waiver(part_id, flag, reason)


def unwaive(session: Session, design_version_id: int, part_id: int, flag: str) -> bool:
    row = session.scalars(
        select(WaiverRow).where(
            WaiverRow.design_version_id == design_version_id,
            WaiverRow.part_id == part_id,
            WaiverRow.flag == flag,
        )
    ).first()
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def run_context(session: Session, design_version_id: int) -> dict[str, Any]:
    """Called by the app layer before a run: waivers and open prompts of this version."""
    repo = StressRepo(session, SystemClock())
    open_prompts: list[ValuePrompt] = repo.open_prompts(design_version_id)
    return {
        "triage_context": {
            "waivers": load_waivers(session, design_version_id),
            "open_prompts": open_prompts,
        }
    }


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Risk triage",
    version=VERSION,
    api_version=API_VERSION,
    requires=("parts", "derating", "effective_stress"),
    optional_requires=(
        "thermal",
        "lifetime",
        "mission_profile",
        "stage",
        "role_map",
        "prompts",
        "triage_context",
    ),
    provides=("refinement",),
    optional=True,
    step=run,
    persist=persist,
    services={
        "load_triage_config": load_config,
        "load_triage_config_file": load_config_file,
        "load_refinement_items": load_results,
        "load_triage_waivers": load_waivers,
        "waive_refinement": waive,
        "unwaive_refinement": unwaive,
        "run_context": run_context,
    },
    migrations_path=Path(__file__).parent / "migrations",
    table_prefix="m3_",
)
