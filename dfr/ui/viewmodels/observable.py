"""Minimal observer helpers so view-models can notify views without Qt."""

from __future__ import annotations

import contextlib
from collections.abc import Callable


class Signal[T]:
    """Callback list. Views connect; view-models emit. Exceptions in one listener do not
    stop the others (a broken panel must not take down the window)."""

    def __init__(self) -> None:
        self._listeners: list[Callable[[T], None]] = []

    def connect(self, fn: Callable[[T], None]) -> Callable[[], None]:
        self._listeners.append(fn)
        return lambda: self.disconnect(fn)

    def disconnect(self, fn: Callable[[T], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def emit(self, value: T) -> None:
        for fn in list(self._listeners):
            with contextlib.suppress(Exception):  # listener isolation
                fn(value)

    def __len__(self) -> int:
        return len(self._listeners)


class Property[T]:
    """A value with a change signal."""

    def __init__(self, value: T) -> None:
        self._value = value
        self.changed: Signal[T] = Signal()

    @property
    def value(self) -> T:
        return self._value

    def set(self, value: T) -> None:
        if value != self._value:
            self._value = value
            self.changed.emit(value)
