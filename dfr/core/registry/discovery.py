"""Find ModuleSpecs in folders, entry points and the user plugin directory (MOD-02, MOD-09).

Discovery never raises for a broken plugin: it records a Diagnostic and moves on.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from dfr.core.contracts.v1 import API_VERSION
from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.extension import ReportSectionSpec, ScreenSpec
from dfr.core.registry.spec import ModuleSpec

MODULE_ATTR = "MODULE"
SCREENS_ATTR = "SCREENS"
REPORT_SECTIONS_ATTR = "REPORT_SECTIONS"
ENTRY_POINT_GROUPS = ("dfr.modules", "dfr.plugins")
BUILTIN_PACKAGES = ("dfr.modules", "dfr.topologies")


@dataclass
class DiscoveryResult:
    modules: list[ModuleSpec] = field(default_factory=list)
    screens: list[ScreenSpec] = field(default_factory=list)
    report_sections: list[ReportSectionSpec] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def by_id(self) -> dict[str, ModuleSpec]:
        return {m.id: m for m in self.modules}


def user_plugin_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "DfR" / "plugins"


def discover(
    *,
    packages: tuple[str, ...] = BUILTIN_PACKAGES,
    entry_points: bool = True,
    plugin_dir: Path | None = None,
    api_version: str = API_VERSION,
) -> DiscoveryResult:
    sink = DiagnosticSink("registry")
    result = DiscoveryResult()
    seen: set[str] = set()

    def accept(mod: ModuleType, origin: str) -> None:
        spec = getattr(mod, MODULE_ATTR, None)
        if spec is None:
            return
        if not isinstance(spec, ModuleSpec):
            sink.error("PLUGIN_BAD_SPEC", f"{origin}: {MODULE_ATTR} is not a ModuleSpec")
            return
        if spec.api_version != api_version:
            sink.error(
                "PLUGIN_API_MISMATCH",
                f"{origin}: module '{spec.id}' declares api_version {spec.api_version!r}, "
                f"this app provides {api_version!r}; module skipped",
            )
            return
        if spec.id in seen:
            sink.error("PLUGIN_DUPLICATE_ID", f"{origin}: duplicate module id '{spec.id}'")
            return
        seen.add(spec.id)
        result.modules.append(spec)
        result.screens.extend(_typed_list(mod, SCREENS_ATTR, ScreenSpec, origin, sink))
        result.report_sections.extend(
            _typed_list(mod, REPORT_SECTIONS_ATTR, ReportSectionSpec, origin, sink)
        )

    for package in packages:
        for mod, origin in _iter_package_modules(package, sink):
            accept(mod, origin)
    if entry_points:
        for mod, origin in _iter_entry_points(sink):
            accept(mod, origin)
    if plugin_dir is not None:
        for mod, origin in _iter_plugin_files(plugin_dir, sink):
            accept(mod, origin)

    result.diagnostics.extend(sink.items)
    return result


def _typed_list(mod: ModuleType, attr: str, kind: type, origin: str, sink: DiagnosticSink) -> list:  # type: ignore[type-arg]
    items = getattr(mod, attr, None)
    if items is None:
        return []
    good = [i for i in items if isinstance(i, kind)]
    if len(good) != len(items):
        sink.error("PLUGIN_BAD_SPEC", f"{origin}: {attr} contains non-{kind.__name__} entries")
    return good


def _iter_package_modules(package: str, sink: DiagnosticSink) -> list[tuple[ModuleType, str]]:
    found: list[tuple[ModuleType, str]] = []
    try:
        pkg = importlib.import_module(package)
    except ModuleNotFoundError:
        return found
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg:
            continue
        name = f"{package}.{info.name}.module"
        try:
            found.append((importlib.import_module(name), name))
        except ModuleNotFoundError as exc:
            if exc.name != name:  # the folder has a module.py but it failed to import
                sink.error("PLUGIN_IMPORT_FAILED", f"{name}: {exc}")
        except Exception as exc:
            sink.error("PLUGIN_IMPORT_FAILED", f"{name}: {exc!r}")
    return found


def _iter_entry_points(sink: DiagnosticSink) -> list[tuple[ModuleType, str]]:
    found: list[tuple[ModuleType, str]] = []
    for group in ENTRY_POINT_GROUPS:
        for ep in importlib.metadata.entry_points(group=group):
            origin = f"entry point {group}:{ep.name}"
            try:
                target = ep.load()
            except Exception as exc:
                sink.error("PLUGIN_IMPORT_FAILED", f"{origin}: {exc!r}")
                continue
            if isinstance(target, ModuleType):
                found.append((target, origin))
            elif isinstance(target, ModuleSpec):
                shim = ModuleType(f"_ep_{ep.name}")
                setattr(shim, MODULE_ATTR, target)
                found.append((shim, origin))
            else:
                sink.error("PLUGIN_BAD_SPEC", f"{origin}: must resolve to a module or ModuleSpec")
    return found


def _iter_plugin_files(folder: Path, sink: DiagnosticSink) -> list[tuple[ModuleType, str]]:
    found: list[tuple[ModuleType, str]] = []
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.py")):
        name = f"dfr_user_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:
            sink.error("PLUGIN_IMPORT_FAILED", f"{path}: {exc!r}")
            continue
        sink.info("PLUGIN_UNSIGNED", f"Loaded unsigned user plugin {path.name}")
        found.append((mod, str(path)))
    return found
