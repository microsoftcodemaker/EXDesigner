"""FMEA library: ``data/fmea/<id>.yaml`` validated against ``data/schemas/fmea.schema.json``;
mode fractions must sum to 1 per class/subtype (PRD 3.9). Errors are diagnostics, never raises."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from dfr.core.contracts import Diagnostic, Severity

MODULE_ID = "m9_fmea"
REPO_DATA = Path(os.environ.get("DFR_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
FMEA_DIR = REPO_DATA / "fmea"
SCHEMA_PATH = REPO_DATA / "schemas" / "fmea.schema.json"
GENERIC = "generic"
FRACTION_TOL = 1e-6


@dataclass(frozen=True)
class Mode:
    id: str
    mode: str
    local_effect: str
    system_effect: str
    severity: int
    detection: int
    fraction: float
    wear_out: bool = False


@dataclass
class FmeaLibrary:
    id: str
    version: int
    sha256: str
    source: str = ""
    fit_upper: tuple[float, ...] = ()
    life_ratio_lower: tuple[float, ...] = ()
    occurrence_source: str = ""
    classes: dict[str, dict[str, tuple[Mode, ...]]] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.version > 0

    def modes_for(self, part_class: str, subtype: str | None) -> tuple[tuple[Mode, ...], str]:
        """(modes, library key used): subtype, else the class default, else ``generic``."""
        by_sub = self.classes.get(part_class, {})
        for key in (subtype or "", "default"):
            if key in by_sub:
                return by_sub[key], f"{part_class}/{key}"
        generic = self.classes.get(GENERIC, {}).get("default", ())
        return generic, f"{GENERIC}/default"


def load_library(library_id: str = "default", *, directory: Path = FMEA_DIR) -> FmeaLibrary:
    path = directory / ("fmea_library.yaml" if library_id == "default" else f"{library_id}.yaml")
    if not path.is_file():
        return FmeaLibrary(library_id, 0, "", diagnostics=[_err(f"FMEA library {path} not found")])
    return load_library_file(path)


def load_library_file(path: Path) -> FmeaLibrary:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data: Any = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        return FmeaLibrary(path.stem, 0, sha, diagnostics=[_err(f"YAML error: {exc}", line)])
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text("utf-8")))
    diags = [
        _err(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}")
        for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]
    if diags:
        return FmeaLibrary(path.stem, 0, sha, diagnostics=diags)
    classes: dict[str, dict[str, tuple[Mode, ...]]] = {}
    for cls, subs in data["classes"].items():
        for sub, modes in subs.items():
            total = sum(float(m["fraction"]) for m in modes)
            ids = [m["id"] for m in modes]
            if abs(total - 1.0) > FRACTION_TOL:
                diags.append(_err(f"classes/{cls}/{sub}: mode fractions sum to {total:g}, not 1"))
                continue
            if len(set(ids)) != len(ids):
                diags.append(_err(f"classes/{cls}/{sub}: duplicate mode id"))
                continue
            classes.setdefault(cls, {})[sub] = tuple(
                Mode(
                    id=m["id"],
                    mode=m["mode"],
                    local_effect=m["local_effect"],
                    system_effect=m["system_effect"],
                    severity=int(m["severity"]),
                    detection=int(m["detection"]),
                    fraction=float(m["fraction"]),
                    wear_out=bool(m.get("wear_out", False)),
                )
                for m in modes
            )
    occ = data["occurrence"]
    for name in ("fit_upper", "life_ratio_lower"):
        seq = [float(x) for x in occ[name]]
        ordered = seq == sorted(seq) if name == "fit_upper" else seq == sorted(seq, reverse=True)
        if not ordered:
            diags.append(_err(f"occurrence/{name} must be monotonic"))
    return FmeaLibrary(
        id=data["id"],
        version=0 if any(d.severity is Severity.ERROR for d in diags) else int(data["version"]),
        sha256=sha,
        source=data["source"],
        fit_upper=tuple(float(x) for x in occ["fit_upper"]),
        life_ratio_lower=tuple(float(x) for x in occ["life_ratio_lower"]),
        occurrence_source=occ["source"],
        classes=classes,
        diagnostics=diags,
    )


def _err(message: str, line_no: int | None = None) -> Diagnostic:
    return Diagnostic(
        code="FMEA_LIBRARY_INVALID",
        severity=Severity.ERROR,
        message=message,
        module=MODULE_ID,
        line_no=line_no,
    )
