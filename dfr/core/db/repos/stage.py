from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from dfr.core.contracts.v1.enums import ProposalProvenance, StageStatus
from dfr.core.contracts.v1.topology import Rail, RoleAssignment, RoleMap, Stage
from dfr.core.db.models import NetRow, PartRow, RailRow, RoleAssignmentRow, StageRow
from dfr.core.ports import Clock


class StageRepo:
    def __init__(self, session: Session, clock: Clock) -> None:
        self.s = session
        self.clock = clock

    def add(self, design_version_id: int, stage: Stage) -> Stage:
        row = StageRow(
            design_version_id=design_version_id,
            pattern_id=stage.pattern_id,
            pattern_version=stage.pattern_version,
            match_confidence=stage.match_confidence,
            netlist_hash=stage.netlist_hash,
            status=stage.status.value,
        )
        self.s.add(row)
        self.s.flush()
        rail_ids: dict[str, int] = {}
        for rail in stage.rails:
            net = self._net_by_name(design_version_id, rail.net_name)
            rrow = RailRow(
                stage_id=row.id,
                rail=rail.rail,
                net_id=net.id if net else None,
                net_name=rail.net_name,
                provenance=rail.provenance.value,
            )
            self.s.add(rrow)
            self.s.flush()
            rail_ids[rail.rail] = rrow.id
        for a in stage.assignments:
            part = self._part_by_refdes(design_version_id, a.refdes)
            if part is None:
                continue  # caller reports unmatched refdes as a Diagnostic
            self.s.add(
                RoleAssignmentRow(
                    stage_id=row.id,
                    part_id=part.id,
                    role=a.role,
                    rail_id=rail_ids.get(a.rail) if a.rail else None,
                    confidence=a.confidence,
                    evidence_json=a.evidence,
                    provenance=a.provenance.value,
                )
            )
        self.s.flush()
        return self.get(row.id)  # type: ignore[return-value]

    def get(self, stage_id: int) -> Stage | None:
        row = self.s.get(
            StageRow,
            stage_id,
            options=[selectinload(StageRow.rails), selectinload(StageRow.assignments)],
        )
        return None if row is None else self._to_contract(row)

    def for_version(self, design_version_id: int) -> list[Stage]:
        stmt = (
            select(StageRow)
            .options(selectinload(StageRow.rails), selectinload(StageRow.assignments))
            .where(StageRow.design_version_id == design_version_id)
            .order_by(StageRow.id)
        )
        return [self._to_contract(r) for r in self.s.scalars(stmt)]

    def confirm(self, stage_id: int) -> None:
        """Mark every assignment and rail user-confirmed; M2 unlocks only after this (REC-06)."""
        row = self.s.get(StageRow, stage_id)
        if row is None:
            return
        now = self.clock.now()
        for a in row.assignments:
            a.provenance = ProposalProvenance.USER.value
            a.confirmed_at = now
        for r in row.rails:
            r.provenance = ProposalProvenance.USER.value
        row.status = StageStatus.CONFIRMED.value
        self.s.flush()

    def mark_stale(self, stage_id: int) -> None:
        row = self.s.get(StageRow, stage_id)
        if row is not None:
            row.status = StageStatus.STALE.value
            self.s.flush()

    def role_map(self, stage_id: int) -> RoleMap:
        stage = self.get(stage_id)
        if stage is None:
            return RoleMap()
        roles: dict[str, list[str]] = {}
        for a in stage.assignments:
            roles.setdefault(a.role, []).append(a.refdes)
        return RoleMap(
            roles={k: tuple(v) for k, v in roles.items()},
            rails={r.rail: r.net_name for r in stage.rails},
        )

    # ----------------------------------------------------------------- helpers
    def _net_by_name(self, design_version_id: int, name: str) -> NetRow | None:
        return self.s.scalar(
            select(NetRow).where(NetRow.design_version_id == design_version_id, NetRow.name == name)
        )

    def _part_by_refdes(self, design_version_id: int, refdes: str) -> PartRow | None:
        return self.s.scalar(
            select(PartRow).where(
                PartRow.design_version_id == design_version_id, PartRow.refdes == refdes
            )
        )

    def _to_contract(self, row: StageRow) -> Stage:
        rails_by_id = {r.id: r for r in row.rails}
        assignments = []
        for a in row.assignments:
            part = self.s.get(PartRow, a.part_id)
            rail = rails_by_id.get(a.rail_id) if a.rail_id is not None else None
            assignments.append(
                RoleAssignment(
                    id=a.id,
                    refdes=part.refdes if part else "",
                    role=a.role,
                    rail=rail.rail if rail else None,
                    confidence=a.confidence,
                    evidence=a.evidence_json,
                    provenance=ProposalProvenance(a.provenance),
                )
            )
        return Stage(
            id=row.id,
            pattern_id=row.pattern_id,
            pattern_version=row.pattern_version,
            match_confidence=row.match_confidence,
            netlist_hash=row.netlist_hash,
            status=StageStatus(row.status),
            rails=[
                Rail(
                    id=r.id,
                    rail=r.rail,
                    net_name=r.net_name,
                    provenance=ProposalProvenance(r.provenance),
                )
                for r in row.rails
            ],
            assignments=assignments,
        )
