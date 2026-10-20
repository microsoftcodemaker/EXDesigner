"""Lifetime model constants from ``data/models/lifetime/*.yaml`` (PRD 3.7: constants are data,
every one carries a source and a confidence). Validated against ``lifetime.schema.json``."""

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

MODULE_ID = "m7_lifetime"
REPO_DATA = Path(os.environ.get("DFR_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
MODELS_DIR = REPO_DATA / "models" / "lifetime"
SCHEMA_PATH = REPO_DATA / "schemas" / "lifetime.schema.json"
HOURS_PER_YEAR = 8766.0


@dataclass(frozen=True)
class CapacitorRule:
    degrees_per_doubling: float
    default_dt0_core_k: float
    life_cap_years: float
    end_of_life: str
    source: str
    confidence: Confidence


@dataclass(frozen=True)
class ProkopowiczVaskas:
    n: float
    ea_ev: float


@dataclass(frozen=True)
class CoffinManson:
    a: float
    n: float


@dataclass
class LifetimeConstants:
    id: str
    version: int
    sha256: str
    electrolytic: CapacitorRule | None = None
    polymer: CapacitorRule | None = None
    kb_ev_per_k: float = 8.617e-5
    mlcc_by_dielectric: dict[str, ProkopowiczVaskas] = field(default_factory=dict)
    mlcc_default: ProkopowiczVaskas = ProkopowiczVaskas(3.0, 1.1)
    mlcc_source: str = ""
    mlcc_confidence: Confidence = Confidence.LOW
    cycling_by_class: dict[str, CoffinManson] = field(default_factory=dict)
    min_delta_tj_k: float = 5.0
    cycling_source: str = ""
    cycling_confidence: Confidence = Confidence.LOW
    connector_source: str = ""
    connector_confidence: Confidence = Confidence.MEDIUM
    description: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def mlcc(self, dielectric: str | None) -> tuple[ProkopowiczVaskas, str]:
        key = (dielectric or "").upper()
        if key in self.mlcc_by_dielectric:
            return self.mlcc_by_dielectric[key], key
        return self.mlcc_default, "default"


def load_constants(
    constants_id: str = "default", *, directory: Path = MODELS_DIR
) -> LifetimeConstants | None:
    path = directory / f"{constants_id}.yaml"
    return load_constants_file(path) if path.is_file() else None


def load_constants_file(path: Path) -> LifetimeConstants:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        return LifetimeConstants(
            path.stem, 0, sha, diagnostics=[_err(f"YAML error: {exc}", getattr(mark, "line", None))]
        )
    diags = validate(data)
    if any(d.severity is Severity.ERROR for d in diags):
        return LifetimeConstants(path.stem, 0, sha, diagnostics=diags)
    m, tc, con = data["mlcc"], data["thermal_cycling"], data["connector"]
    return LifetimeConstants(
        id=data["id"],
        version=int(data["version"]),
        sha256=sha,
        electrolytic=_cap_rule(data["electrolytic"]),
        polymer=_cap_rule(data["polymer"]),
        kb_ev_per_k=float(m["kb_ev_per_k"]),
        mlcc_by_dielectric={
            k.upper(): ProkopowiczVaskas(float(v["n"]), float(v["ea_ev"]))
            for k, v in m["dielectrics"].items()
        },
        mlcc_default=ProkopowiczVaskas(float(m["default"]["n"]), float(m["default"]["ea_ev"])),
        mlcc_source=m["source"],
        mlcc_confidence=Confidence(m["confidence"]),
        cycling_by_class={
            k: CoffinManson(float(v["a"]), float(v["n"])) for k, v in tc["classes"].items()
        },
        min_delta_tj_k=float(tc["min_delta_tj_k"]),
        cycling_source=tc["source"],
        cycling_confidence=Confidence(tc["confidence"]),
        connector_source=con["source"],
        connector_confidence=Confidence(con["confidence"]),
        description=data.get("description", ""),
        diagnostics=diags,
    )


def _cap_rule(d: dict[str, Any]) -> CapacitorRule:
    return CapacitorRule(
        degrees_per_doubling=float(d["degrees_per_doubling"]),
        default_dt0_core_k=float(d["default_dt0_core_k"]),
        life_cap_years=float(d["life_cap_years"]),
        end_of_life=str(d.get("end_of_life", "")),
        source=d["source"],
        confidence=Confidence(d["confidence"]),
    )


def validate(data: Any) -> list[Diagnostic]:
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    return [
        _err(f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}")
        for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]


def _err(message: str, line_no: int | None = None) -> Diagnostic:
    return Diagnostic(
        code="LIFETIME_CONSTANTS_INVALID",
        severity=Severity.ERROR,
        message=message,
        module=MODULE_ID,
        line_no=line_no,
    )
