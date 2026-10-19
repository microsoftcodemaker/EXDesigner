from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.contracts.v1.enums import RunStatus, Severity, Tier
from dfr.core.contracts.v1.run import AnalysisRun
from dfr.core.contracts.v1.spec import RunConfig
from dfr.core.contracts.v1.stress import StressKey, StressValue
from dfr.core.db.models import AnalysisRunRow, DiagnosticRow, EffectiveStressRow
from dfr.core.ports import Clock


class ImmutableRunError(RuntimeError):
    """Raised on any attempt to modify a finished run (DAT-01)."""


class RunRepo:
    def __init__(self, session: Session, clock: Clock) -> None:
        self.s = session
        self.clock = clock

    def start(
        self,
        design_version_id: int,
        config: RunConfig,
        *,
        tier_level: Tier = Tier.T1,
        parent_run_id: int | None = None,
        ruleset_hash: str | None = None,
        model_set: dict[str, str] | None = None,
    ) -> AnalysisRun:
        row = AnalysisRunRow(
            design_version_id=design_version_id,
            parent_run_id=parent_run_id,
            tier_level=int(tier_level),
            ruleset_id=config.ruleset_id,
            ruleset_hash=ruleset_hash,
            model_set_json=json.dumps(model_set or {}, sort_keys=True),
            config_json=config.model_dump_json(),
            started_at=self.clock.now(),
            status=RunStatus.RUNNING.value,
        )
        self.s.add(row)
        self.s.flush()
        return self._to_contract(row)

    def snapshot_effective(self, run_id: int, effective: dict[StressKey, StressValue]) -> None:
        self._writable(run_id)
        for key, value in effective.items():
            if value.id is None:
                msg = "effective stress values must be persisted before snapshotting"
                raise ValueError(msg)
            self.s.add(
                EffectiveStressRow(
                    run_id=run_id,
                    part_id=key.part_id,
                    param=key.param,
                    scenario=key.scenario,
                    stress_value_id=value.id,
                )
            )
        self.s.flush()

    def finish(self, run_id: int, status: RunStatus = RunStatus.COMPLETED) -> AnalysisRun:
        row = self._writable(run_id)
        row.finished_at = self.clock.now()
        row.status = status.value
        self.s.flush()
        return self._to_contract(row)

    def get(self, run_id: int) -> AnalysisRun | None:
        row = self.s.get(AnalysisRunRow, run_id)
        return None if row is None else self._to_contract(row)

    def for_version(self, design_version_id: int) -> list[AnalysisRun]:
        stmt = (
            select(AnalysisRunRow)
            .where(AnalysisRunRow.design_version_id == design_version_id)
            .order_by(AnalysisRunRow.id)
        )
        return [self._to_contract(r) for r in self.s.scalars(stmt)]

    def chain(self, run_id: int) -> list[AnalysisRun]:
        """The run and its ancestors, oldest first (Tier 2 refinement chain)."""
        out: list[AnalysisRun] = []
        current = self.get(run_id)
        while current is not None:
            out.append(current)
            current = self.get(current.parent_run_id) if current.parent_run_id else None
        return list(reversed(out))

    def effective_ids(self, run_id: int) -> dict[StressKey, int]:
        stmt = select(EffectiveStressRow).where(EffectiveStressRow.run_id == run_id)
        return {
            StressKey(r.part_id, r.param, r.scenario): r.stress_value_id
            for r in self.s.scalars(stmt)
        }

    def _writable(self, run_id: int) -> AnalysisRunRow:
        row = self.s.get(AnalysisRunRow, run_id)
        if row is None:
            msg = f"run {run_id} not found"
            raise LookupError(msg)
        if row.finished_at is not None:
            msg = f"run {run_id} is finished and immutable"
            raise ImmutableRunError(msg)
        return row

    def _to_contract(self, row: AnalysisRunRow) -> AnalysisRun:
        diags = tuple(
            Diagnostic(
                code=d.code,
                severity=Severity(d.severity),
                message=d.message,
                module=d.module,
                part_id=d.part_id,
                line_no=d.line_no,
            )
            for d in row.diagnostics
        )
        return AnalysisRun(
            id=row.id,
            design_version_id=row.design_version_id,
            parent_run_id=row.parent_run_id,
            tier_level=Tier(row.tier_level),
            ruleset_id=row.ruleset_id,
            ruleset_hash=row.ruleset_hash,
            model_set=json.loads(row.model_set_json),
            config=RunConfig.model_validate_json(row.config_json),
            started_at=row.started_at,
            finished_at=row.finished_at,
            status=RunStatus(row.status),
            diagnostics=diags,
        )


class DiagnosticRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add_many(self, run_id: int, diagnostics: Iterable[Diagnostic]) -> int:
        run = self.s.get(AnalysisRunRow, run_id)
        if run is None:
            msg = f"run {run_id} not found"
            raise LookupError(msg)
        if run.finished_at is not None:
            msg = f"run {run_id} is finished and immutable"
            raise ImmutableRunError(msg)
        n = 0
        for d in diagnostics:
            self.s.add(
                DiagnosticRow(
                    run_id=run_id,
                    module=d.module,
                    code=d.code,
                    severity=d.severity.value,
                    part_id=d.part_id,
                    line_no=d.line_no,
                    message=d.message,
                )
            )
            n += 1
        self.s.flush()
        return n

    def for_run(self, run_id: int) -> list[Diagnostic]:
        stmt = (
            select(DiagnosticRow).where(DiagnosticRow.run_id == run_id).order_by(DiagnosticRow.id)
        )
        return [
            Diagnostic(
                code=d.code,
                severity=Severity(d.severity),
                message=d.message,
                module=d.module,
                part_id=d.part_id,
                line_no=d.line_no,
            )
            for d in self.s.scalars(stmt)
        ]
