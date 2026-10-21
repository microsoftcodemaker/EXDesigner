"""M8: failure rate and MTBF (PRD 3.8). Owns ``m8_failure_rate_result`` (branch of the same name).

Step inputs: parts, effective_stress; optional thermal (Tj for piT), lifetime (PoF roll-up),
mission_profile (target life), converter_spec (Ta), config (``failure_rate_method`` picks one
table id; None = every table with data, each as its own result so constant-rate and wear-out
numbers are never mixed). ``RunConfig.extra`` keys ``fr_environment`` / ``fr_quality`` override
the table defaults. Output: ``failure_rate`` = list[FailureRateResult].
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
    FailureRateResult,
    LifetimeResult,
    MissionProfile,
    Part,
    PartFailureRate,
    RunConfig,
    StressKey,
    StressValue,
    ThermalResult,
)
from dfr.core.db.base import Base
from dfr.modules.m8_failure_rate.engine import parts_stress
from dfr.modules.m8_failure_rate.pof import weibull_rollup
from dfr.modules.m8_failure_rate.report import comparison, sections
from dfr.modules.m8_failure_rate.tables import (
    MODULE_ID,
    PARTS_STRESS_METHOD,
    POF_METHOD,
    FailureRateTable,
    load_table,
    load_table_file,
    load_tables,
)

VERSION = "0.1.0"
ENV_KEY = "fr_environment"
QUALITY_KEY = "fr_quality"


class FailureRateResultRow(Base):
    __tablename__ = "m8_failure_rate_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    table_id: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[str | None] = mapped_column(String(10))
    system_lambda_fit: Mapped[float | None] = mapped_column(Float)
    system_mtbf_h: Mapped[float | None] = mapped_column(Float)
    system_mttf_h: Mapped[float | None] = mapped_column(Float)
    b10_h: Mapped[float | None] = mapped_column(Float)
    per_part_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    curve_json: Mapped[str | None] = mapped_column(Text)
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    excluded_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


def compute_failure_rates(
    parts: list[Part],
    effective: Mapping[StressKey, StressValue],
    tables: Mapping[str, FailureRateTable],
    *,
    method: str | None = None,
    thermal: list[ThermalResult] | None = None,
    lifetime: list[LifetimeResult] | None = None,
    profile: MissionProfile | None = None,
    t_ambient: float = 25.0,
    environment: str | None = None,
    quality: str | None = None,
    sink: DiagnosticSink | None = None,
) -> list[FailureRateResult]:
    """One result per selected table; wear-out and constant-rate results stay separate."""
    sink = sink if sink is not None else DiagnosticSink(MODULE_ID)
    profile = profile or MissionProfile()
    chosen = [tables[method]] if method and method in tables else list(tables.values())
    if method and method not in tables:
        sink.error("FAILURE_RATE_NO_TABLE", f"failure_rate_method {method!r} has no table")
        return []
    results: list[FailureRateResult] = []
    for t in chosen:
        sink.extend(t.diagnostics)
        if t.version == 0:
            continue
        if t.method == PARTS_STRESS_METHOD:
            r = parts_stress(parts, effective, t, thermal, t_ambient, environment, quality)
        elif t.method == POF_METHOD:
            if lifetime is None:
                sink.info("FAILURE_RATE_POF_SKIPPED", f"{t.id}: no M7 lifetime results")
                continue
            r = weibull_rollup(lifetime, t, target_life_h=profile.target_life_hours)
        else:  # pragma: no cover - schema forbids
            continue
        results.append(r)
        _summarise(sink, r)
    return results


def _summarise(sink: DiagnosticSink, r: FailureRateResult) -> None:
    if r.system_lambda_fit is not None and r.system_mtbf_h is not None:
        sink.info(
            "FAILURE_RATE_SUMMARY",
            f"{r.method}: lambda_sys {r.system_lambda_fit:.1f} FIT, MTBF "
            f"{r.system_mtbf_h / 8766:.1f} y over {len(r.per_part)} part(s), "
            f"{len(r.excluded_part_ids)} excluded ({(r.confidence or Confidence.LOW).value})",
        )
    elif r.system_mttf_h is not None:
        b10 = f"{r.b10_h / 8766:.1f} y" if r.b10_h is not None else "n/a"
        sink.info(
            "FAILURE_RATE_SUMMARY",
            f"{r.method}: MTTF {r.system_mttf_h / 8766:.1f} y, B10 {b10} over "
            f"{len(r.per_part)} mechanism(s); no MTBF for wear-out",
        )
    else:
        sink.warning(
            "FAILURE_RATE_NOT_AVAILABLE",
            f"{r.method}: no part could be rated ({len(r.excluded_part_ids)} excluded); "
            f"{r.assumptions[-1]}",
        )


def run(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink(MODULE_ID)
    tables: Mapping[str, FailureRateTable] = ctx.get_or("failure_rate_tables") or load_tables()
    if not tables:
        sink.error("FAILURE_RATE_NO_TABLES", "no failure-rate tables found; M8 skipped")
        return StepResult.from_sink(sink, failure_rate=[])
    cfg: RunConfig = ctx.get_or("config") or RunConfig()
    spec = ctx.get_or("converter_spec")
    results = compute_failure_rates(
        ctx.get("parts"),
        ctx.get("effective_stress"),
        tables,
        method=cfg.failure_rate_method,
        thermal=ctx.get_or("thermal"),
        lifetime=ctx.get_or("lifetime"),
        profile=ctx.get_or("mission_profile"),
        t_ambient=spec.t_ambient if spec is not None else 25.0,
        environment=cfg.extra.get(ENV_KEY),
        quality=cfg.extra.get(QUALITY_KEY),
        sink=sink,
    )
    return StepResult.from_sink(sink, failure_rate=results)


def persist(session: Session, run_id: int, result: StepResult) -> dict[str, Any] | None:
    for r in result.outputs.get("failure_rate", []):
        session.add(
            FailureRateResultRow(
                run_id=run_id,
                method=r.method,
                table_id=r.table_id,
                confidence=r.confidence.value if r.confidence else None,
                system_lambda_fit=r.system_lambda_fit,
                system_mtbf_h=r.system_mtbf_h,
                system_mttf_h=r.system_mttf_h,
                b10_h=r.b10_h,
                per_part_json=json.dumps([p.model_dump() for p in r.per_part]),
                curve_json=json.dumps(r.reliability_curve) if r.reliability_curve else None,
                assumptions_json=json.dumps(r.assumptions),
                excluded_json=json.dumps({str(k): v for k, v in r.excluded_reasons.items()}),
            )
        )
    session.flush()
    return None


def load_results(session: Session, run_id: int) -> list[FailureRateResult]:
    rows = session.scalars(
        select(FailureRateResultRow)
        .where(FailureRateResultRow.run_id == run_id)
        .order_by(FailureRateResultRow.id)
    )
    out = []
    for r in rows:
        excluded = {int(k): v for k, v in json.loads(r.excluded_json).items()}
        out.append(
            FailureRateResult(
                method=r.method,
                per_part=[PartFailureRate.model_validate(p) for p in json.loads(r.per_part_json)],
                system_lambda_fit=r.system_lambda_fit,
                system_mtbf_h=r.system_mtbf_h,
                reliability_curve=[tuple(p) for p in json.loads(r.curve_json)]
                if r.curve_json
                else None,
                assumptions=json.loads(r.assumptions_json),
                excluded_part_ids=sorted(excluded),
                system_mttf_h=r.system_mttf_h,
                b10_h=r.b10_h,
                table_id=r.table_id,
                confidence=Confidence(r.confidence) if r.confidence else None,
                excluded_reasons=excluded,
            )
        )
    return out


def run_options() -> dict[str, dict[str, list[str]]]:
    """Per table: the environment / quality keys its lookup factors accept (default first),
    so a UI can offer the ``fr_environment`` / ``fr_quality`` run settings without guessing."""
    out: dict[str, dict[str, list[str]]] = {}
    for tid, t in load_tables().items():
        keys: dict[str, list[str]] = {"environment": [], "quality": []}
        for entry in t.entries.values():
            for f in entry.factors:
                if f.kind == "lookup" and f.by in keys:
                    keys[f.by] += [k for k in f.table if k not in keys[f.by]]
        for name, default in (("environment", t.environment), ("quality", t.quality)):
            if default:
                keys[name] = [default, *(k for k in keys[name] if k != default)]
        out[tid] = keys
    return out


def bundle_extras(session: Session, run_id: int) -> dict[str, Any]:
    return {"failure_rate": load_results(session, run_id)}


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Failure rate and MTBF",
    version=VERSION,
    api_version=API_VERSION,
    requires=("parts", "effective_stress"),
    optional_requires=("thermal", "lifetime", "mission_profile", "converter_spec", "config"),
    provides=("failure_rate",),
    optional=True,
    step=run,
    persist=persist,
    services={
        "compute_failure_rates": compute_failure_rates,
        "load_failure_rate_tables": load_tables,
        "load_failure_rate_table": load_table,
        "load_failure_rate_table_file": load_table_file,
        "load_failure_rate_results": load_results,
        "failure_rate.run_options": run_options,
        "failure_rate.comparison": comparison,
        "report.bundle_extras": bundle_extras,
        "report.sections": sections,
    },
    migrations_path=Path(__file__).parent / "migrations",
    table_prefix="m8_",
)
