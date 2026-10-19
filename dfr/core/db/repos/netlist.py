from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from dfr.core.contracts.v1.enums import AutoUserProvenance, NetKind, PinFunctionProvenance
from dfr.core.contracts.v1.netlist import Net, Pin
from dfr.core.db.models import NetRow, PartRow, PinRow


class NetlistRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ----------------------------------------------------------------- nets
    def add_net(self, design_version_id: int, net: Net) -> Net:
        row = NetRow(
            design_version_id=design_version_id,
            name=net.name,
            normalized_name=net.normalized_name,
            kind=net.kind.value,
            kind_provenance=net.kind_provenance.value,
        )
        self.s.add(row)
        self.s.flush()
        return self._net(row)

    def nets_for_version(self, design_version_id: int) -> list[Net]:
        stmt = (
            select(NetRow)
            .where(NetRow.design_version_id == design_version_id)
            .order_by(NetRow.name)
        )
        return [self._net(r) for r in self.s.scalars(stmt)]

    def net_by_name(self, design_version_id: int, name: str) -> Net | None:
        stmt = select(NetRow).where(
            NetRow.design_version_id == design_version_id, NetRow.name == name
        )
        row = self.s.scalar(stmt)
        return None if row is None else self._net(row)

    def set_net_kind(self, net_id: int, kind: NetKind) -> None:
        """User override of the auto classification (NET-04)."""
        row = self.s.get(NetRow, net_id)
        if row is not None:
            row.kind = kind.value
            row.kind_provenance = AutoUserProvenance.USER.value
            self.s.flush()

    # ----------------------------------------------------------------- pins
    def add_pin(self, part_id: int, pin: Pin, net_id: int | None) -> Pin:
        row = PinRow(
            part_id=part_id,
            net_id=net_id,
            pin_id=pin.pin_id,
            function=pin.function,
            function_provenance=pin.function_provenance.value if pin.function_provenance else None,
            pintype=pin.pintype,
        )
        self.s.add(row)
        self.s.flush()
        return self._pin(row)

    def pins_for_part(self, part_id: int) -> list[Pin]:
        stmt = select(PinRow).where(PinRow.part_id == part_id).order_by(PinRow.pin_id)
        return [self._pin(r) for r in self.s.scalars(stmt)]

    def pins_on_net(self, net_id: int) -> list[Pin]:
        stmt = select(PinRow).where(PinRow.net_id == net_id)
        return [self._pin(r) for r in self.s.scalars(stmt)]

    def set_pin_function(
        self, pin_db_id: int, function: str, provenance: PinFunctionProvenance
    ) -> None:
        row = self.s.get(PinRow, pin_db_id)
        if row is not None:
            row.function = function
            row.function_provenance = provenance.value
            self.s.flush()

    # ----------------------------------------------------------------- mapping
    @staticmethod
    def _net(row: NetRow) -> Net:
        return Net(
            id=row.id,
            name=row.name,
            normalized_name=row.normalized_name,
            kind=NetKind(row.kind),
            kind_provenance=AutoUserProvenance(row.kind_provenance),
        )

    def _pin(self, row: PinRow) -> Pin:
        part = self.s.get(PartRow, row.part_id)
        net = self.s.get(NetRow, row.net_id) if row.net_id is not None else None
        return Pin(
            id=row.id,
            refdes=part.refdes if part else "",
            pin_id=row.pin_id,
            net_name=net.name if net else None,
            function=row.function,
            function_provenance=PinFunctionProvenance(row.function_provenance)
            if row.function_provenance
            else None,
            pintype=row.pintype,
        )
