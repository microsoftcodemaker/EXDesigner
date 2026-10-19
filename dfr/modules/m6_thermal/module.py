"""M6: thermal calculator (PRD 3.6). Owns ``m6_thermal_result`` (branch ``m6_thermal``).

Per part and scenario: P = p_loss stress (if any). If the part has an ``rds_on`` rating and an
``i_rms`` stress, the conduction part is iterated with Rds_on(Tj); any remaining loss is held
constant. theta_ja comes from ratings (``theta_ja``) or a heatsink chain (``theta_jc``,
``theta_cs``, ``theta_sa``). Resistors use the derating temperature curve instead (M5) and
are skipped here. Parts with loss but no theta get a diagnostic and no result (never a guess).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from dfr.api import API_VERSION, DiagnosticSink, ModuleSpec, RunContext, StepResult
from dfr.core.contracts import Part, PartClass, StressKey, StressValue, ThermalResult
from dfr.core.db.base import Base
from dfr.core.equations.losses import RDS_ON_ALPHA_DEFAULT, rds_on_at
from dfr.core.equations.thermal import ThermalPath, solve_tj

MODULE_ID = "m6_thermal"
VERSION = "0.1.0"
SKIP_CLASSES = {PartClass.RESISTOR, PartClass.CONNECTOR, PartClass.TEST_POINT, PartClass.OTHER}


class ThermalResultRow(Base):
    __tablename__ = "m6_thermal_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scenario: Mapped[str] = mapped_column(String(30), nullable=False)
    tj: Mapped[float] = mapped_column(Float, nullable=False)
    tc: Mapped[float | None] = mapped_column(Float)
    p_total: Mapped[float] = mapped_column(Float, nullable=False)
    delta_tj_cycles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    runaway_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


def solve_thermal(
    parts: list[Part],
    effective: Mapping[StressKey, StressValue],
    t_ambient: float,
    *,
    sink: DiagnosticSink | None = None,
) -> list[ThermalResult]:
    sink = sink if sink is not None else DiagnosticSink(MODULE_ID)
    results: list[ThermalResult] = []
    for part in parts:
        if part.id is None or part.dnp or part.part_class in SKIP_CLASSES:
            continue
        path = _path(part)
        rds = part.ratings.get("rds_on")
        tj_max = part.ratings.get("tj_max")
        by_scenario = _stress_by_scenario(part.id, effective)
        if not by_scenario:
            continue
        for scenario, rows in by_scenario.items():
            p_loss = rows.get("p_loss")
            i_rms = rows.get("i_rms") or rows.get("i_rms_hs")
            if p_loss is None and (rds is None or i_rms is None):
                continue  # nothing to heat this part with
            if path.total is None:
                sink.warning(
                    "THERMAL_NO_THETA",
                    f"{part.refdes}: loss known but no theta_ja (or theta_jc + theta_sa) rating; "
                    "Tj not computed",
                    part_id=part.id,
                )
                break
            p_other = p_loss.value if p_loss else 0.0
            i = i_rms.value if (i_rms and rds) else 0.0
            if rds and i_rms and p_loss:
                # Remove the 25 degC conduction share so it can be re-added at Tj.
                p_other = max(
                    0.0, p_other - i**2 * rds_on_at(rds.value, 25.0, RDS_ON_ALPHA_DEFAULT)
                )
            sol = solve_tj(
                ta=t_ambient,
                path=path,
                p_other=p_other,
                i_rms=i,
                rds_on_25=rds.value if rds else None,
                tj_max=tj_max.value if tj_max else None,
            )
            used = tuple(v.id for v in (p_loss, i_rms) if v is not None and v.id is not None)
            if sol.runaway:
                sink.error(
                    "THERMAL_RUNAWAY_RISK",
                    f"{part.refdes} [{scenario}]: Tj {sol.tj:.0f} degC exceeds "
                    f"Tj_max or diverges; thermal_runaway_risk",
                    part_id=part.id,
                )
            elif not sol.converged:
                sink.warning(
                    "THERMAL_NOT_CONVERGED",
                    f"{part.refdes} [{scenario}]: Rds_on(Tj) loop did not "
                    f"converge in {sol.iterations} iterations",
                    part_id=part.id,
                )
            results.append(
                ThermalResult(
                    part_id=part.id,
                    scenario=scenario,
                    tj=sol.tj,
                    tc=sol.tc,
                    runaway_flag=sol.runaway,
                    stress_value_ids=used,
                )
            )
    return results


def _rating(part: Part, name: str) -> float | None:
    r = part.ratings.get(name)
    return r.value if r is not None else None


def _path(part: Part) -> ThermalPath:
    return ThermalPath(
        theta_ja=_rating(part, "theta_ja"),
        theta_jc=_rating(part, "theta_jc"),
        theta_cs=_rating(part, "theta_cs") or 0.0,
        theta_sa=_rating(part, "theta_sa"),
    )


def _stress_by_scenario(
    part_id: int, effective: Mapping[StressKey, StressValue]
) -> dict[str, dict[str, StressValue]]:
    out: dict[str, dict[str, StressValue]] = {}
    for key, v in effective.items():
        if key.part_id == part_id:
            out.setdefault(key.scenario, {})[key.param] = v
    return out


def run(ctx: RunContext) -> StepResult:
    sink = DiagnosticSink(MODULE_ID)
    spec = ctx.get_or("converter_spec")
    ta = spec.t_ambient if spec else ctx.get_or("t_ambient", 25.0)
    results = solve_thermal(ctx.get("parts"), ctx.get("effective_stress"), ta, sink=sink)
    return StepResult.from_sink(sink, thermal=results)


def load_results(session: Session, run_id: int) -> list[ThermalResult]:
    from sqlalchemy import select  # noqa: PLC0415

    rows = session.scalars(select(ThermalResultRow).where(ThermalResultRow.run_id == run_id))
    return [
        ThermalResult(
            part_id=r.part_id, scenario=r.scenario, tj=r.tj, tc=r.tc, runaway_flag=r.runaway_flag
        )
        for r in rows
    ]


def persist(session: Session, run_id: int, result: StepResult) -> dict[str, Any] | None:
    import json  # noqa: PLC0415

    for r in result.outputs.get("thermal", []):
        session.add(
            ThermalResultRow(
                run_id=run_id,
                part_id=r.part_id,
                scenario=r.scenario,
                tj=r.tj,
                tc=r.tc,
                p_total=0.0,
                delta_tj_cycles_json=json.dumps(list(r.delta_tj_cycles)),
                runaway_flag=r.runaway_flag,
            )
        )
    session.flush()
    return None


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Thermal calculator",
    version=VERSION,
    api_version=API_VERSION,
    requires=("parts", "effective_stress"),
    optional_requires=("stress",),
    provides=("thermal",),
    optional=True,
    step=run,
    persist=persist,
    services={"solve_thermal": solve_thermal, "load_thermal_results": load_results},
    migrations_path=Path(__file__).parent / "migrations",
    table_prefix="m6_",
)
