"""M9: FMEA generator (PRD 3.9, T38). Owns ``m9_fmea_row`` and ``m9_fmea_override`` (branch
``m9_fmea``).

Step inputs: parts; optional failure_rate (M8), lifetime (M7), mission_profile, role_map and
``fmea_context`` (the version's user overrides, loaded by the ``run_context`` service).
Output: ``fmea`` = list[FmeaRow] sorted by RPN. Overrides persist per design version and part +
mode, so they survive re-runs (FME-02); they take effect on the next run (runs are immutable),
while ``fmea_rows_with_overrides`` shows them at once.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from dfr.api import API_VERSION, DiagnosticSink, ModuleSpec, RunContext, StepResult
from dfr.core.contracts import FmeaRow
from dfr.core.db.base import Base
from dfr.core.db.models import AnalysisRunRow
from dfr.core.db.types import UtcDateTime
from dfr.core.ports import Clock
from dfr.modules.m9_fmea.engine import Override, generate
from dfr.modules.m9_fmea.library import MODULE_ID, load_library, load_library_file
from dfr.modules.m9_fmea.report import sections

VERSION = "0.1.0"
CSV_COLUMNS = ("refdes", "mode", "local_effect", "system_effect", "S", "O", "D", "RPN",
               "O_basis", "lambda_mode_fit", "life_ratio", "flags", "note")  # fmt: skip


class FmeaRowRow(Base):
    __tablename__ = "m9_fmea_row"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode_id: Mapped[str] = mapped_column(String(60), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    local_effect: Mapped[str] = mapped_column(Text, nullable=False)
    system_effect: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrence: Mapped[int] = mapped_column(Integer, nullable=False)
    detection: Mapped[int] = mapped_column(Integer, nullable=False)
    rpn: Mapped[int] = mapped_column(Integer, nullable=False)
    flags_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurrence_basis: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    lambda_fit: Mapped[float | None] = mapped_column(Float)
    life_ratio: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)


class FmeaOverrideRow(Base):
    __tablename__ = "m9_fmea_override"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_version_id: Mapped[int] = mapped_column(
        ForeignKey("design_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode_id: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[int | None] = mapped_column(Integer)
    occurrence: Mapped[int | None] = mapped_column(Integer)
    detection: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


# ----------------------------------------------------------------------------- step


def run(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink(MODULE_ID)
    lib = ctx.get_or("fmea_library") or load_library()
    sink.extend(lib.diagnostics)
    if not lib.ok:
        sink.error("FMEA_NO_LIBRARY", "FMEA library unusable; FMEA skipped")
        return StepResult.from_sink(sink, fmea=[])
    extra: dict[str, Any] = ctx.get_or("fmea_context") or {}
    rows = generate(
        ctx.get("parts"),
        lib,
        failure_rates=ctx.get_or("failure_rate", []),
        lifetime=ctx.get_or("lifetime", []),
        profile=ctx.get_or("mission_profile"),
        roles=ctx.get_or("role_map"),
        overrides=extra.get("overrides", []),
        sink=sink,
    )
    return StepResult.from_sink(sink, fmea=rows)


def persist(session: Session, run_id: int, result: StepResult) -> dict[str, Any] | None:
    stored: list[FmeaRow] = []
    for r in result.outputs.get("fmea", []):
        row = FmeaRowRow(
            run_id=run_id,
            part_id=r.part_id,
            mode_id=r.mode_id,
            mode=r.mode,
            local_effect=r.local_effect,
            system_effect=r.system_effect,
            severity=r.severity,
            occurrence=r.occurrence,
            detection=r.detection,
            rpn=r.rpn,
            flags_json=json.dumps(r.source_flags, sort_keys=True),
            occurrence_basis=r.occurrence_basis,
            lambda_fit=r.lambda_fit,
            life_ratio=r.life_ratio,
            note=r.mitigation_note,
        )
        session.add(row)
        session.flush()
        stored.append(r.model_copy(update={"id": row.id}))
    return {"fmea": stored}


# ----------------------------------------------------------------------------- services


def load_results(session: Session, run_id: int) -> list[FmeaRow]:
    rows = session.scalars(
        select(FmeaRowRow)
        .where(FmeaRowRow.run_id == run_id)
        .order_by(FmeaRowRow.rpn.desc(), FmeaRowRow.part_id, FmeaRowRow.mode_id)
    )
    return [
        FmeaRow(
            id=r.id,
            part_id=r.part_id,
            mode=r.mode,
            local_effect=r.local_effect,
            system_effect=r.system_effect,
            severity=r.severity,
            occurrence=r.occurrence,
            detection=r.detection,
            source_flags=json.loads(r.flags_json),
            mitigation_note=r.note,
            mode_id=r.mode_id,
            occurrence_basis=r.occurrence_basis,
            lambda_fit=r.lambda_fit,
            life_ratio=r.life_ratio,
        )
        for r in rows
    ]


def load_overrides(session: Session, design_version_id: int) -> list[Override]:
    rows = session.scalars(
        select(FmeaOverrideRow).where(FmeaOverrideRow.design_version_id == design_version_id)
    )
    return [
        Override(r.part_id, r.mode_id, r.severity, r.occurrence, r.detection, r.note) for r in rows
    ]


def set_override(
    session: Session,
    clock: Clock,
    design_version_id: int,
    part_id: int,
    mode_id: str,
    *,
    severity: int | None = None,
    occurrence: int | None = None,
    detection: int | None = None,
    note: str | None = None,
) -> Override:
    """Store a user S/O/D edit (FME-02, timestamped); None leaves that rating to the library."""
    for name, v in (("severity", severity), ("occurrence", occurrence), ("detection", detection)):
        if v is not None and not 1 <= v <= 10:
            msg = f"{name} must be 1-10, got {v}"
            raise ValueError(msg)
    row = session.scalars(
        select(FmeaOverrideRow).where(
            FmeaOverrideRow.design_version_id == design_version_id,
            FmeaOverrideRow.part_id == part_id,
            FmeaOverrideRow.mode_id == mode_id,
        )
    ).first()
    if row is None:
        row = FmeaOverrideRow(design_version_id=design_version_id, part_id=part_id, mode_id=mode_id)
        session.add(row)
    row.severity, row.occurrence, row.detection, row.note = severity, occurrence, detection, note
    row.updated_at = clock.now()
    session.flush()
    return Override(part_id, mode_id, severity, occurrence, detection, note)


def clear_override(session: Session, design_version_id: int, part_id: int, mode_id: str) -> bool:
    row = session.scalars(
        select(FmeaOverrideRow).where(
            FmeaOverrideRow.design_version_id == design_version_id,
            FmeaOverrideRow.part_id == part_id,
            FmeaOverrideRow.mode_id == mode_id,
        )
    ).first()
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def rows_with_overrides(session: Session, run_id: int) -> list[FmeaRow]:
    """A run's rows with the version's *current* overrides applied (what the next run stores)."""
    run = session.get(AnalysisRunRow, run_id)
    if run is None:
        return []
    ov = {(o.part_id, o.mode_id): o for o in load_overrides(session, run.design_version_id)}
    out: list[FmeaRow] = []
    for stored in load_results(session, run_id):
        r, o = stored, ov.get((stored.part_id, stored.mode_id))
        if o is not None:
            flags = dict(r.source_flags)
            upd: dict[str, Any] = {"mitigation_note": o.note}
            for key, attr, v in (
                ("S", "severity", o.severity),
                ("O", "occurrence", o.occurrence),
                ("D", "detection", o.detection),
            ):
                if v is not None:
                    upd[attr], flags[key] = v, "user"
            r = stored.model_copy(update={**upd, "source_flags": flags})
        out.append(r)
    return sorted(out, key=lambda r: (-r.rpn, r.part_id, r.mode_id))


def to_csv(rows: list[FmeaRow], refdes: dict[int, str]) -> str:
    """FME-03 CSV export (UTF-8, one row per part + mode)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        w.writerow(
            [
                refdes.get(r.part_id, str(r.part_id)),
                r.mode,
                r.local_effect,
                r.system_effect,
                r.severity,
                r.occurrence,
                r.detection,
                r.rpn,
                r.occurrence_basis,
                f"{r.lambda_fit:.4g}" if r.lambda_fit is not None else "",
                f"{r.life_ratio:.3g}" if r.life_ratio is not None else "",
                ";".join(f"{k}={v}" for k, v in sorted(r.source_flags.items())),
                r.mitigation_note or "",
            ]
        )
    return buf.getvalue()


def run_context(session: Session, design_version_id: int) -> dict[str, Any]:
    return {"fmea_context": {"overrides": load_overrides(session, design_version_id)}}


def bundle_extras(session: Session, run_id: int) -> dict[str, Any]:
    return {"fmea": load_results(session, run_id)}


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="FMEA generator",
    version=VERSION,
    api_version=API_VERSION,
    requires=("parts",),
    optional_requires=(
        "failure_rate",
        "lifetime",
        "mission_profile",
        "role_map",
        "fmea_context",
        "fmea_library",
    ),
    provides=("fmea",),
    optional=True,
    step=run,
    persist=persist,
    services={
        "load_fmea_library": load_library,
        "load_fmea_library_file": load_library_file,
        "load_fmea_rows": load_results,
        "fmea_rows_with_overrides": rows_with_overrides,
        "load_fmea_overrides": load_overrides,
        "set_fmea_override": set_override,
        "clear_fmea_override": clear_override,
        "fmea_csv": to_csv,
        "run_context": run_context,
        "report.bundle_extras": bundle_extras,
        "report.sections": sections,
    },
    migrations_path=Path(__file__).parent / "migrations",
    table_prefix="m9_",
)
