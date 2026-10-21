"""FMEA row generator (PRD 3.9, FME-01/02). Pure function of parts, M8 rates, M7 lives, the
library and the user's overrides.

Occurrence (1-10):
    wear-out mode with an M7 life : O from life / target through ``life_ratio_lower``
    otherwise, with an M8 constant-rate per-part FIT :
        lambda_mode = lambda_part * fraction, O from ``fit_upper`` (<= bound -> that O)
    neither : O = 10, basis "no_data" (conservative rank, never a guessed rate)
Severity / Detection: library defaults. RPN = S * O * D. A user override (part_id + mode id)
replaces S, O and/or D and is flagged "user"; a changed lambda only moves an O that is not
overridden.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from dfr.core.contracts import (
    FailureRateResult,
    FmeaRow,
    LifetimeResult,
    MissionProfile,
    Part,
    PartClass,
    RoleMap,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.modules.m9_fmea.library import GENERIC, FmeaLibrary, Mode

SKIP_CLASSES = {PartClass.TEST_POINT}


@dataclass(frozen=True)
class Override:
    part_id: int
    mode_id: str
    severity: int | None = None
    occurrence: int | None = None
    detection: int | None = None
    note: str | None = None


def occurrence_from_fit(lambda_fit: float, fit_upper: Sequence[float]) -> int:
    """PRD 3.9 scale: first bound not exceeded gives O (1-based); above the last bound -> 10."""
    for i, bound in enumerate(fit_upper):
        if lambda_fit <= bound:
            return i + 1
    return 10


def occurrence_from_life(ratio: float, life_ratio_lower: Sequence[float]) -> int:
    """Wear-out: first bound the life/target ratio reaches gives O; below the last -> 10."""
    for i, bound in enumerate(life_ratio_lower):
        if ratio >= bound:
            return i + 1
    return 10


def part_rates(results: Iterable[FailureRateResult]) -> dict[int, tuple[float, str]]:
    """part_id -> (FIT, method) from the first constant-rate result that covers the part."""
    out: dict[int, tuple[float, str]] = {}
    for r in results:
        if r.system_lambda_fit is None:
            continue  # PoF roll-up: wear-out, not a constant rate
        for p in r.per_part:
            out.setdefault(p.part_id, (p.lambda_fit, r.method))
    return out


def shortest_lives(results: Iterable[LifetimeResult]) -> dict[int, float]:
    out: dict[int, float] = {}
    for r in results:
        if r.life_hours is not None:
            out[r.part_id] = min(out.get(r.part_id, r.life_hours), r.life_hours)
    return out


def generate(
    parts: Sequence[Part],
    library: FmeaLibrary,
    *,
    failure_rates: Iterable[FailureRateResult] = (),
    lifetime: Iterable[LifetimeResult] = (),
    profile: MissionProfile | None = None,
    roles: RoleMap | None = None,
    overrides: Iterable[Override] = (),
    sink: DiagnosticSink | None = None,
) -> list[FmeaRow]:
    sink = sink or DiagnosticSink("m9_fmea")
    rates = part_rates(failure_rates)
    lives = shortest_lives(lifetime)
    target = (profile or MissionProfile()).target_life_hours
    role_of = {r: role for role, refs in (roles.roles if roles else {}).items() for r in refs}
    ov: Mapping[tuple[int, str], Override] = {(o.part_id, o.mode_id): o for o in overrides}
    rows: list[FmeaRow] = []
    generic: list[str] = []
    for part in parts:
        if part.dnp or part.id is None or part.part_class in SKIP_CLASSES:
            continue
        modes, key = library.modes_for(part.part_class.value, part.subtype)
        if key.startswith(GENERIC):
            generic.append(part.refdes)
        role = role_of.get(part.refdes, "part")
        if role == "other":
            role = "part"
        for m in modes:
            rows.append(
                _row(part, m, role, rates.get(part.id), lives.get(part.id), target, library, ov)
            )
    if generic:
        sink.warning(
            "FMEA_GENERIC_ROWS",
            f"{len(generic)} part(s) not in the FMEA library, generic rows used: "
            f"{', '.join(generic)}",
        )
    no_data = sorted({r.part_id for r in rows if r.occurrence_basis == "no_data"})
    if no_data:
        sink.info(
            "FMEA_O_NO_DATA",
            f"{len(no_data)} part(s) without a failure rate or life: O = 10 (conservative)",
        )
    sink.info("FMEA_SUMMARY", f"{len(rows)} FMEA rows; library {library.id} v{library.version}")
    return sorted(rows, key=lambda r: (-r.rpn, r.part_id, r.mode_id))


def _row(  # noqa: PLR0917
    part: Part,
    m: Mode,
    role: str,
    rate: tuple[float, str] | None,
    life: float | None,
    target: float,
    lib: FmeaLibrary,
    ov: Mapping[tuple[int, str], Override],
) -> FmeaRow:
    assert part.id is not None
    lambda_mode = rate[0] * m.fraction if rate is not None else None
    ratio = life / target if life is not None and target > 0 else None
    if m.wear_out and ratio is not None:
        occ, basis = occurrence_from_life(ratio, lib.life_ratio_lower), "life"
    elif rate is not None and lambda_mode is not None:
        occ, basis = occurrence_from_fit(lambda_mode, lib.fit_upper), f"fit:{rate[1]}"
    else:
        occ, basis = 10, "no_data"
    flags = {"S": "seed", "O": basis, "D": "seed"}
    sev, det, note = m.severity, m.detection, None
    o = ov.get((part.id, m.id))
    if o is not None:
        if o.severity is not None:
            sev, flags["S"] = o.severity, "user"
        if o.occurrence is not None:
            occ, flags["O"] = o.occurrence, "user"
        if o.detection is not None:
            det, flags["D"] = o.detection, "user"
        note = o.note
    return FmeaRow(
        part_id=part.id,
        mode=m.mode,
        local_effect=m.local_effect,
        system_effect=m.system_effect.format(refdes=part.refdes, role=role),
        severity=sev,
        occurrence=occ,
        detection=det,
        source_flags=flags,
        mitigation_note=note,
        mode_id=m.id,
        occurrence_basis=flags["O"],
        lambda_fit=lambda_mode,
        life_ratio=ratio,
    )
