"""M5: derating checker. Owns ``m5_derating_result`` (branch ``m5_derating``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from dfr.api import API_VERSION, DiagnosticSink, ModuleSpec, RunContext, StepResult
from dfr.core.contracts import DeratingResult, DeratingStatus
from dfr.core.db.base import Base
from dfr.modules.m5_derating.checker import evaluate_derating
from dfr.modules.m5_derating.ruleset import MODULE_ID, load_ruleset, load_ruleset_file

VERSION = "0.1.0"


class DeratingResultRow(Base):
    __tablename__ = "m5_derating_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    param: Mapped[str] = mapped_column(String(30), nullable=False)
    stress: Mapped[float | None] = mapped_column(Float)
    limit: Mapped[float | None] = mapped_column(Float)
    rating: Mapped[float | None] = mapped_column(Float)
    ratio: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    margin: Mapped[float | None] = mapped_column(Float)
    rule_id: Mapped[str] = mapped_column(String(50), nullable=False)
    stress_value_ids: Mapped[str] = mapped_column(String(200), nullable=False, default="")


def run(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink(MODULE_ID)
    cfg = ctx.get("config")
    ruleset = ctx.get_or("ruleset") or load_ruleset(cfg.ruleset_id)
    if ruleset is None:
        sink.error(
            "DERATING_NO_RULESET", f"rule set {cfg.ruleset_id!r} not found; derating skipped"
        )
        return StepResult.from_sink(sink, derating=[], ruleset_hash=None)
    sink.extend(ruleset.diagnostics)
    if not ruleset.rules:
        return StepResult.from_sink(sink, derating=[], ruleset_hash=ruleset.sha256)
    spec = ctx.get_or("converter_spec")
    results = evaluate_derating(
        ctx.get("parts"),
        ctx.get("effective_stress"),
        ruleset,
        thermal=ctx.get_or("thermal"),
        t_ambient=spec.t_ambient if spec else None,
        sink=sink,
    )
    counts = {s: sum(r.status is s for r in results) for s in {r.status for r in results}}
    sink.info(
        "DERATING_SUMMARY",
        ", ".join(f"{k.value}={v}" for k, v in sorted(counts.items(), key=lambda kv: kv[0].value))
        or "no rows",
    )
    return StepResult.from_sink(sink, derating=results, ruleset_hash=ruleset.sha256)


def load_results(session: Session, run_id: int) -> list[DeratingResult]:
    """Stored derating rows for a run (used by reporting and compare screens)."""
    from sqlalchemy import select  # noqa: PLC0415

    rows = session.scalars(select(DeratingResultRow).where(DeratingResultRow.run_id == run_id))
    return [
        DeratingResult(
            part_id=r.part_id,
            param=r.param,
            stress=r.stress,
            limit=r.limit,
            rating=r.rating,
            ratio=r.ratio,
            status=DeratingStatus(r.status),
            margin=r.margin,
            rule_id=r.rule_id,
            stress_value_ids=tuple(int(i) for i in r.stress_value_ids.split(",") if i),
        )
        for r in rows
    ]


def persist(session: Session, run_id: int, result: StepResult) -> dict[str, Any] | None:
    rows: list[DeratingResult] = result.outputs.get("derating", [])
    for r in rows:
        session.add(
            DeratingResultRow(
                run_id=run_id,
                part_id=r.part_id,
                param=r.param,
                stress=r.stress,
                limit=r.limit,
                rating=r.rating,
                ratio=r.ratio,
                status=r.status.value,
                margin=r.margin,
                rule_id=r.rule_id,
                stress_value_ids=",".join(str(i) for i in r.stress_value_ids),
            )
        )
    session.flush()
    return None


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Derating checker",
    version=VERSION,
    api_version=API_VERSION,
    requires=("parts", "effective_stress", "config"),
    optional_requires=("thermal", "stress"),
    provides=("derating", "ruleset_hash"),
    optional=False,
    step=run,
    persist=persist,
    services={
        "load_ruleset": load_ruleset,
        "load_ruleset_file": load_ruleset_file,
        "load_derating_results": load_results,
    },
    migrations_path=Path(__file__).parent / "migrations",
    table_prefix="m5_",
)
