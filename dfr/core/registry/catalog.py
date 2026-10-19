"""Typed registries for screens, report sections, and topology patterns/templates (MOD-06)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol, TypeVar

from dfr.core.extension import ReportSectionSpec, ScreenSpec, TopologyPattern, TopologyTemplate


class _HasId(Protocol):
    @property
    def id(self) -> str: ...


T = TypeVar("T", bound=_HasId)


class SpecRegistry[T: _HasId]:
    """Ordered, id-keyed collection. Re-registering the same id replaces the entry."""

    def __init__(self, items: Iterable[T] = ()) -> None:
        self._items: dict[str, T] = {}
        for item in items:
            self.register(item)

    def register(self, item: T) -> None:
        self._items[item.id] = item

    def unregister(self, item_id: str) -> None:
        self._items.pop(item_id, None)

    def get(self, item_id: str) -> T | None:
        return self._items.get(item_id)

    def __contains__(self, item_id: object) -> bool:
        return item_id in self._items

    def __iter__(self) -> Iterator[T]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def ids(self) -> list[str]:
        return list(self._items)


class ScreenRegistry(SpecRegistry[ScreenSpec]):
    def visible(self, present_modules: Iterable[str]) -> list[ScreenSpec]:
        """Screens whose required modules are all present, ordered for the stepper."""
        present = set(present_modules)
        shown = [s for s in self if set(s.requires) <= present]
        return sorted(shown, key=lambda s: (s.step, s.order, s.id))


class ReportSectionRegistry(SpecRegistry[ReportSectionSpec]):
    def available(self, present_modules: Iterable[str]) -> list[ReportSectionSpec]:
        present = set(present_modules)
        shown = [s for s in self if set(s.requires) <= present]
        return sorted(shown, key=lambda s: (s.order, s.id))


class TopologyRegistry:
    """Pairs each TopologyTemplate with the TopologyPattern it names."""

    def __init__(self) -> None:
        self.patterns: SpecRegistry[TopologyPattern] = SpecRegistry()
        self.templates: SpecRegistry[TopologyTemplate] = SpecRegistry()

    def register_pattern(self, pattern: TopologyPattern) -> None:
        self.patterns.register(pattern)

    def register_template(self, template: TopologyTemplate) -> None:
        self.templates.register(template)

    def template_for_pattern(self, pattern_id: str) -> list[TopologyTemplate]:
        return [t for t in self.templates if t.pattern_id == pattern_id]

    def unpaired_templates(self) -> list[TopologyTemplate]:
        return [t for t in self.templates if t.pattern_id not in self.patterns]
