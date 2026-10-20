"""Tier 2 stress import from a simple CSV (PRD 3.2 mode c, reduced form; OPC-08 waveform
windows arrive later). One row = one already-reduced number from the user's simulator or bench.

Columns (header required, any order, case-insensitive):
    refdes, param, stat, scenario, value, unit, source, tool, note
``scenario``, ``tool`` and ``note`` are optional. ``source`` is ``measured`` or ``simulated``.
All-or-nothing: any error rejects the whole file with line-numbered diagnostics. Rows are
stored with ``tier=2``, ``tool="csv:<name>"`` and the file's SHA-256 as ``tool_version``.
An open prompt matching (part, param, scenario) is answered by the row.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from dfr.core.contracts import Diagnostic, Severity, Source, Stat, StressValue, Tier
from dfr.core.db.repos import PartRepo, StressRepo
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.ports import Clock
from dfr.core.units import UnitError, validate_unit
from dfr.modules.m2_conditions.infer import MODULE_ID

REQUIRED = ("refdes", "param", "stat", "value", "unit", "source")
OPTIONAL = ("scenario", "tool", "note")
T2_SOURCES = (Source.MEASURED, Source.SIMULATED)


@dataclass
class T2Import:
    stored: list[StressValue]
    answered_prompt_ids: list[int]
    sha256: str
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(d.severity is Severity.ERROR for d in self.diagnostics)


def parse_t2_csv(
    data: str, name: str, refdes_to_part: dict[str, int], clock: Clock
) -> tuple[list[StressValue], str, list[Diagnostic]]:
    """Validate and convert; returns (values, sha256, diagnostics). Values empty on any error."""
    sink = DiagnosticSink(MODULE_ID)
    sha = hashlib.sha256(data.encode("utf-8")).hexdigest()
    reader = csv.DictReader(io.StringIO(data))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    reader.fieldnames = headers
    missing = [c for c in REQUIRED if c not in headers]
    unknown = [h for h in headers if h and h not in (*REQUIRED, *OPTIONAL)]
    if missing:
        sink.error("T2_CSV_HEADER", f"missing column(s): {', '.join(missing)}", line_no=1)
    for h in unknown:
        sink.warning("T2_CSV_UNKNOWN_COLUMN", f"column {h!r} ignored", line_no=1)
    if sink.has_errors:
        return [], sha, list(sink.items)
    now = clock.now()
    values: list[StressValue] = []
    for line_no, row in enumerate(reader, start=2):
        value = _row(row, line_no, refdes_to_part, name, sha, now, sink)
        if value is not None:
            values.append(value)
    if not values and not sink.has_errors:
        sink.error("T2_CSV_EMPTY", "no data rows", line_no=1)
    return ([] if sink.has_errors else values), sha, list(sink.items)


def import_t2_csv(
    session: Session, clock: Clock, design_version_id: int, data: str, name: str
) -> T2Import:
    """Parse, then store every row and answer matching open prompts. Nothing written on error."""
    parts = PartRepo(session).for_version(design_version_id)
    refdes_to_part = {p.refdes: p.id for p in parts if p.id is not None}
    values, sha, diags = parse_t2_csv(data, name, refdes_to_part, clock)
    if not values:
        return T2Import([], [], sha, diags)
    repo = StressRepo(session, clock)
    open_prompts = {
        (p.part_id, p.param, p.scenario): p.id
        for p in repo.open_prompts(design_version_id)
        if p.id is not None
    }
    stored: list[StressValue] = []
    answered: list[int] = []
    for v in values:
        pid = open_prompts.pop((v.part_id, v.param, v.scenario), None)
        if pid is None:
            stored.append(repo.add(v))
        else:
            stored.append(repo.answer_prompt(pid, v))
            answered.append(pid)
    sink = DiagnosticSink(MODULE_ID)
    sink.info(
        "T2_CSV_IMPORTED",
        f"{name}: {len(stored)} Tier 2 value(s) stored, {len(answered)} prompt(s) answered",
    )
    return T2Import(stored, answered, sha, [*diags, *sink.items])


# ----------------------------------------------------------------------------- helpers


def _row(  # noqa: PLR0917
    row: dict[str, str | None],
    line_no: int,
    refdes_to_part: dict[str, int],
    name: str,
    sha: str,
    now: datetime,
    sink: DiagnosticSink,
) -> StressValue | None:
    def get(k: str) -> str:
        return (row.get(k) or "").strip()

    if not any(get(k) for k in REQUIRED):
        return None  # blank line
    ok = True
    refdes = get("refdes")
    part_id = refdes_to_part.get(refdes)
    if part_id is None:
        sink.error("T2_CSV_REFDES", f"unknown refdes {refdes!r}", line_no=line_no)
        ok = False
    param = get("param")
    if not param:
        sink.error("T2_CSV_PARAM", "param is empty", line_no=line_no)
        ok = False
    stat = _enum(Stat, get("stat"), "stat", line_no, sink)
    source = _enum(Source, get("source"), "source", line_no, sink)
    if source is not None and source not in T2_SOURCES:
        sink.error(
            "T2_CSV_SOURCE",
            f"source {source.value!r} is not Tier 2; use measured or simulated",
            line_no=line_no,
        )
        ok = False
    try:
        value = float(get("value"))
    except ValueError:
        sink.error("T2_CSV_VALUE", f"value {get('value')!r} is not a number", line_no=line_no)
        ok = False
        value = 0.0
    unit = get("unit")
    try:
        validate_unit(unit)
    except UnitError as exc:
        sink.error("T2_CSV_UNIT", str(exc), line_no=line_no)
        ok = False
    if not ok or stat is None or source is None or part_id is None:
        return None
    tool = get("tool")
    return StressValue(
        part_id=part_id,
        param=param,
        value=value,
        unit=unit,
        stat=stat,
        scenario=get("scenario") or "nominal",
        source=source,
        tier=Tier.T2,
        tool=f"csv:{name}" + (f" ({tool})" if tool else ""),
        tool_version=sha[:12],
        timestamp=now,
        note=get("note") or None,
    )


def _enum[E: StrEnum](
    kind: type[E], text: str, col: str, line_no: int, sink: DiagnosticSink
) -> E | None:
    try:
        return kind(text.lower())
    except ValueError:
        allowed = ", ".join(m.value for m in kind)
        sink.error(f"T2_CSV_{col.upper()}", f"{col} {text!r} not in {{{allowed}}}", line_no=line_no)
        return None
