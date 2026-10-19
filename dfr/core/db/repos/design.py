from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dfr.core.db.models import Design, DesignVersion
from dfr.core.ports import Clock


class DesignRepo:
    def __init__(self, session: Session, clock: Clock) -> None:
        self.s = session
        self.clock = clock

    def create(self, name: str, topology_template: str | None = None) -> Design:
        row = Design(name=name, topology_template=topology_template, created_at=self.clock.now())
        self.s.add(row)
        self.s.flush()
        return row

    def get(self, design_id: int) -> Design | None:
        return self.s.get(Design, design_id)

    def list_all(self) -> list[Design]:
        return list(self.s.scalars(select(Design).order_by(Design.created_at, Design.id)))

    def rename(self, design_id: int, name: str) -> None:
        row = self.s.get(Design, design_id)
        if row is not None:
            row.name = name
            self.s.flush()

    def delete(self, design_id: int) -> None:
        row = self.s.get(Design, design_id)
        if row is not None:
            self.s.delete(row)
            self.s.flush()

    def new_version(
        self,
        design_id: int,
        *,
        bom_hash: str | None = None,
        netlist_hash: str | None = None,
        netlist_format: str | None = None,
        note: str | None = None,
    ) -> DesignVersion:
        """Versions are append-only: created whenever BOM, ratings or netlist change."""
        current = self.s.scalar(
            select(func.max(DesignVersion.version_no)).where(DesignVersion.design_id == design_id)
        )
        row = DesignVersion(
            design_id=design_id,
            version_no=(current or 0) + 1,
            bom_hash=bom_hash,
            netlist_hash=netlist_hash,
            netlist_format=netlist_format,
            note=note,
            created_at=self.clock.now(),
        )
        self.s.add(row)
        self.s.flush()
        return row

    def versions(self, design_id: int) -> list[DesignVersion]:
        stmt = (
            select(DesignVersion)
            .where(DesignVersion.design_id == design_id)
            .order_by(DesignVersion.version_no)
        )
        return list(self.s.scalars(stmt))

    def latest_version(self, design_id: int) -> DesignVersion | None:
        stmt = (
            select(DesignVersion)
            .where(DesignVersion.design_id == design_id)
            .order_by(DesignVersion.version_no.desc())
            .limit(1)
        )
        return self.s.scalar(stmt)
