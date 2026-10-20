"""Failure-rate tables from ``data/models/failure_rate/*.yaml`` (PRD 3.8).

Two table kinds share one schema (``failure_rate.schema.json``):

* ``parts_stress`` -- a constant-rate method (MIL-HDBK-217F, SR-332 Method I, ...): per part
  class/subtype a base rate and named pi factors. The shipped 217F and SR-332 files have empty
  ``classes`` (owner decision: never transcribe); the user imports a filled file in the format
  of ``docs/failure_rate_tables.md``.
* ``pof_weibull`` -- Weibull shape factors per M7 mechanism for the physics-of-failure roll-up.

Every table carries ``source`` and ``confidence``; results echo both.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from dfr.core.contracts import Confidence, Diagnostic, Severity

MODULE_ID = "m8_failure_rate"
REPO_DATA = Path(os.environ.get("DFR_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
TABLES_DIR = REPO_DATA / "models" / "failure_rate"
SCHEMA_PATH = REPO_DATA / "schemas" / "failure_rate.schema.json"
POF_METHOD = "pof_weibull"
PARTS_STRESS_METHOD = "parts_stress"


@dataclass(frozen=True)
class Factor:
    """One pi factor: how to compute it from the part, its stress and the run settings."""

    name: str
    kind: str  # constant | lookup | arrhenius | stress_ratio | value_curve
    value: float | None = None
    by: str | None = None  # lookup: quality | environment | attribute:<name>
    table: dict[str, float] = field(default_factory=dict)
    default: float | None = None
    ea_ev: float | None = None
    t_ref_c: float = 25.0
    requires_tj: bool = False
    param: str | None = None
    rating: str | None = None
    curve: tuple[tuple[float, float], ...] = ()
    log: bool = False


@dataclass(frozen=True)
class Entry:
    """Base rate and factors for one class/subtype."""

    part_class: str
    subtype: str  # "default" = any subtype of the class
    form: str  # product | ic_sum
    lambda_b: float
    c1: float
    c2: float
    factors: tuple[Factor, ...]
    source: str


@dataclass
class FailureRateTable:
    id: str
    method: str
    version: int
    sha256: str
    source: str = ""
    standard: str = ""
    license: str = ""
    description: str = ""
    confidence: Confidence = Confidence.LOW
    rate_unit: str = "fit"
    environment: str = ""
    quality: str = ""
    kb_ev_per_k: float = 8.617e-5
    entries: dict[tuple[str, str], Entry] = field(default_factory=dict)
    betas: dict[str, float] = field(default_factory=dict)
    beta_sources: dict[str, str] = field(default_factory=dict)
    default_beta: float = 2.0
    life_is: str = "eta"
    grid_t_min_h: float = 1.0
    grid_points: int = 400
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def fit_per_unit(self) -> float:
        return 1000.0 if self.rate_unit == "per_1e6_h" else 1.0

    @property
    def is_empty(self) -> bool:
        return not self.entries if self.method == PARTS_STRESS_METHOD else not self.betas

    def entry_for(self, part_class: str, subtype: str | None) -> Entry | None:
        if subtype and (part_class, subtype) in self.entries:
            return self.entries[(part_class, subtype)]
        return self.entries.get((part_class, "default"))

    def beta_for(self, mechanism: str) -> tuple[float, str]:
        if mechanism in self.betas:
            return self.betas[mechanism], self.beta_sources.get(mechanism, self.source)
        return self.default_beta, f"default_beta ({self.source})"


def load_tables(directory: Path = TABLES_DIR) -> dict[str, FailureRateTable]:
    """Every ``*.yaml`` in the folder keyed by table id (invalid files keep their diagnostics)."""
    out: dict[str, FailureRateTable] = {}
    if directory.is_dir():
        for path in sorted(directory.glob("*.yaml")):
            t = load_table_file(path)
            out[t.id] = t
    return out


def load_table(table_id: str, *, directory: Path = TABLES_DIR) -> FailureRateTable | None:
    path = directory / f"{table_id}.yaml"
    return load_table_file(path) if path.is_file() else None


def load_table_file(path: Path) -> FailureRateTable:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        return FailureRateTable(
            path.stem,
            "invalid",
            0,
            sha,
            diagnostics=[_err(f"YAML error: {exc}", getattr(mark, "line", None))],
        )
    diags = validate(data)
    if any(d.severity is Severity.ERROR for d in diags):
        return FailureRateTable(path.stem, "invalid", 0, sha, diagnostics=diags)
    defaults = data.get("defaults", {})
    t = FailureRateTable(
        id=data["id"],
        method=data["method"],
        version=int(data["version"]),
        sha256=sha,
        source=data["source"],
        standard=data.get("standard", ""),
        license=data.get("license", ""),
        description=data.get("description", ""),
        confidence=Confidence(data["confidence"]),
        rate_unit=data.get("rate_unit", "fit"),
        environment=str(defaults.get("environment", "")),
        quality=str(defaults.get("quality", "")),
        kb_ev_per_k=float(defaults.get("kb_ev_per_k", 8.617e-5)),
        default_beta=float(data.get("default_beta", 2.0)),
        life_is=data.get("life_is", "eta"),
        grid_t_min_h=float(data.get("grid", {}).get("t_min_h", 1.0)),
        grid_points=int(data.get("grid", {}).get("points", 400)),
        diagnostics=diags,
    )
    for cls, subtypes in data.get("classes", {}).items():
        for sub, e in subtypes.items():
            t.entries[(cls, sub)] = _entry(cls, sub, e, data["source"])
    for mech, m in data.get("mechanisms", {}).items():
        t.betas[mech] = float(m["beta"])
        t.beta_sources[mech] = str(m.get("source", data["source"]))
    return t


def _entry(cls: str, sub: str, e: dict[str, Any], source: str) -> Entry:
    return Entry(
        part_class=cls,
        subtype=sub,
        form=e.get("form", "product"),
        lambda_b=float(e.get("lambda_b", 0.0)),
        c1=float(e.get("c1", 0.0)),
        c2=float(e.get("c2", 0.0)),
        factors=tuple(_factor(name, f) for name, f in e["factors"].items()),
        source=str(e.get("source", source)),
    )


def _factor(name: str, f: dict[str, Any]) -> Factor:
    return Factor(
        name=name,
        kind=f["kind"],
        value=_opt(f.get("value")),
        by=f.get("by"),
        table={str(k): float(v) for k, v in f.get("table", {}).items()},
        default=_opt(f.get("default")),
        ea_ev=_opt(f.get("ea_ev")),
        t_ref_c=float(f.get("t_ref_c", 25.0)),
        requires_tj=bool(f.get("requires_tj", False)),
        param=f.get("param"),
        rating=f.get("rating"),
        curve=tuple((float(x), float(y)) for x, y in f.get("curve", [])),
        log=bool(f.get("log", False)),
    )


def _opt(v: Any) -> float | None:
    return None if v is None else float(v)


def validate(data: Any) -> list[Diagnostic]:
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    return [
        _err(f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}")
        for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]


def _err(message: str, line_no: int | None = None) -> Diagnostic:
    return Diagnostic(
        code="FAILURE_RATE_TABLE_INVALID",
        severity=Severity.ERROR,
        message=message,
        module=MODULE_ID,
        line_no=line_no,
    )
