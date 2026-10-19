"""Screen discovery (MOD-06). A screen is a folder ``dfr/ui/screens/<id>/screen.py`` exposing
``SCREEN: ScreenSpec`` and ``build(vm) -> QWidget``. The stepper and document tabs are built
from this registry; a screen whose required modules are absent is hidden.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dfr.core.extension import ScreenSpec


@dataclass(frozen=True)
class ScreenEntry:
    spec: ScreenSpec
    build: Callable[[Any], Any]  # (ShellViewModel) -> QWidget


def discover_screens(present_modules: list[str]) -> list[ScreenEntry]:
    import dfr.ui.screens as pkg  # noqa: PLC0415

    found: list[ScreenEntry] = []
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg:
            continue
        try:
            mod = importlib.import_module(f"dfr.ui.screens.{info.name}.screen")
        except ModuleNotFoundError:
            continue
        spec = getattr(mod, "SCREEN", None)
        build = getattr(mod, "build", None)
        if not isinstance(spec, ScreenSpec) or not callable(build):
            continue
        if set(spec.requires) <= set(present_modules):
            found.append(ScreenEntry(spec, build))
    return sorted(found, key=lambda e: (e.spec.order, e.spec.id))
