from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from dfr.core.contracts.v1.enums import PromptOrigin, PromptStatus, Source, Stat, Tier
from dfr.core.contracts.v1.spec import ValuePrompt
from dfr.core.contracts.v1.stress import StressKey, StressValue
from dfr.core.db.models import PartRow, StressValueRow, ValuePromptRow
from dfr.core.ports import Clock


def resolve_effective_stress(values: Iterable[StressValue]) -> dict[StressKey, StressValue]:
    """Precedence: pinned manual > Tier 2 (newest timestamp) > Tier 1 (newest). PRD section 2.6."""
    best: dict[StressKey, StressValue] = {}
    for v in values:
        cur = best.get(v.key)
        if cur is None or _rank(v) > _rank(cur):
            best[v.key] = v
    return best


def _rank(v: StressValue) -> tuple[int, int, float]:
    return (1 if v.pinned else 0, int(v.tier), v.timestamp.timestamp())


class StressRepo:
    """stress_value rows are append-only; there is deliberately no update or delete."""

    def __init__(self, session: Session, clock: Clock) -> None:
        self.s = session
        self.clock = clock

    def add(self, value: StressValue, *, prompt_id: int | None = None) -> StressValue:
        row = StressValueRow(
            part_id=value.part_id,
            param=value.param,
            value=value.value,
            unit=value.unit,
            stat=value.stat.value,
            scenario=value.scenario,
            source=value.source.value,
            tier=int(value.tier),
            tool=value.tool,
            tool_version=value.tool_version,
            timestamp=value.timestamp,
            pinned=value.pinned,
            note=value.note,
            prompt_id=prompt_id,
        )
        self.s.add(row)
        self.s.flush()
        return self._to_contract(row)

    def add_many(self, values: Iterable[StressValue]) -> list[StressValue]:
        return [self.add(v) for v in values]

    def get(self, value_id: int) -> StressValue | None:
        row = self.s.get(StressValueRow, value_id)
        return None if row is None else self._to_contract(row)

    def for_part(self, part_id: int) -> list[StressValue]:
        stmt = (
            select(StressValueRow)
            .where(StressValueRow.part_id == part_id)
            .order_by(StressValueRow.timestamp, StressValueRow.id)
        )
        return [self._to_contract(r) for r in self.s.scalars(stmt)]

    def for_version(self, design_version_id: int) -> list[StressValue]:
        stmt = (
            select(StressValueRow)
            .join(PartRow, PartRow.id == StressValueRow.part_id)
            .where(PartRow.design_version_id == design_version_id)
            .order_by(StressValueRow.timestamp, StressValueRow.id)
        )
        return [self._to_contract(r) for r in self.s.scalars(stmt)]

    def effective_for_version(self, design_version_id: int) -> dict[StressKey, StressValue]:
        return resolve_effective_stress(self.for_version(design_version_id))

    # ----------------------------------------------------------------- prompts
    def add_prompt(self, design_version_id: int, prompt: ValuePrompt) -> ValuePrompt:
        row = ValuePromptRow(
            design_version_id=design_version_id,
            part_id=prompt.part_id,
            param=prompt.param,
            stat=prompt.stat,
            scenario=prompt.scenario,
            reason=prompt.reason,
            how_to_obtain=prompt.how_to_obtain,
            origin=prompt.origin.value,
            status=prompt.status.value,
        )
        self.s.add(row)
        self.s.flush()
        return self._prompt(row)

    def open_prompts(self, design_version_id: int) -> list[ValuePrompt]:
        stmt = select(ValuePromptRow).where(
            ValuePromptRow.design_version_id == design_version_id,
            ValuePromptRow.status == PromptStatus.OPEN.value,
        )
        return [self._prompt(r) for r in self.s.scalars(stmt)]

    def answer_prompt(self, prompt_id: int, value: StressValue) -> StressValue:
        row = self.s.get(ValuePromptRow, prompt_id)
        if row is None:
            msg = f"prompt {prompt_id} not found"
            raise LookupError(msg)
        stored = self.add(value, prompt_id=prompt_id)
        row.status = PromptStatus.ANSWERED.value
        row.answered_at = self.clock.now()
        self.s.flush()
        return stored

    def skip_prompt(self, prompt_id: int) -> None:
        row = self.s.get(ValuePromptRow, prompt_id)
        if row is not None:
            row.status = PromptStatus.SKIPPED.value
            self.s.flush()

    # ----------------------------------------------------------------- mapping
    @staticmethod
    def _to_contract(row: StressValueRow) -> StressValue:
        return StressValue(
            id=row.id,
            part_id=row.part_id,
            param=row.param,
            value=row.value,
            unit=row.unit,
            stat=Stat(row.stat),
            scenario=row.scenario,
            source=Source(row.source),
            tier=Tier(row.tier),
            tool=row.tool,
            tool_version=row.tool_version,
            timestamp=row.timestamp,
            pinned=row.pinned,
            note=row.note,
        )

    @staticmethod
    def _prompt(row: ValuePromptRow) -> ValuePrompt:
        return ValuePrompt(
            id=row.id,
            part_id=row.part_id,
            param=row.param,
            stat=row.stat,
            scenario=row.scenario,
            reason=row.reason,
            how_to_obtain=row.how_to_obtain,
            origin=PromptOrigin(row.origin),
            status=PromptStatus(row.status),
        )
