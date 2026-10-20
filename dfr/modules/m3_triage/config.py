"""Triage thresholds, weights and the F4 blind-spot table: YAML in ``data/triage``, validated
against ``data/schemas/triage.schema.json`` with line-numbered errors (PRD 3.3, TRI-01)."""

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

MODULE_ID = "m3_triage"
REPO_DATA = Path(os.environ.get("DFR_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
TRIAGE_DIR = REPO_DATA / "triage"
SCHEMA_PATH = REPO_DATA / "schemas" / "triage.schema.json"


@dataclass(frozen=True)
class BlindSpot:
    id: str
    topologies: tuple[str, ...]
    roles: tuple[str, ...]
    param: str
    stat: str
    scenario: str
    weight: float
    reason: str
    how: str
    source: str


@dataclass
class TriageConfig:
    id: str
    version: int
    sha256: str
    margin_threshold: float = 0.15
    tj_proximity_c: float = 20.0
    mode_boundary: float = 0.20
    w1_margin: float = 0.35
    w2_thermal: float = 0.25
    w3_lifetime: float = 0.25
    w4_blind_spot: float = 0.15
    no_data: float = 1.0
    blind_spots: list[BlindSpot] = field(default_factory=list)
    description: str = ""
    source: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def spots_for(self, topology: str | None, roles: set[str]) -> list[BlindSpot]:
        return [
            b for b in self.blind_spots if topology in b.topologies and roles.intersection(b.roles)
        ]


def load_config(config_id: str = "default", *, directory: Path = TRIAGE_DIR) -> TriageConfig | None:
    path = directory / f"{config_id}.yaml"
    return load_config_file(path) if path.is_file() else None


def load_config_file(path: Path) -> TriageConfig:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        return TriageConfig(
            path.stem, 0, sha, diagnostics=[_err(f"YAML error: {exc}", getattr(mark, "line", None))]
        )
    diags = validate(data, path)
    if any(d.severity is Severity.ERROR for d in diags):
        return TriageConfig(path.stem, 0, sha, diagnostics=diags)
    th, w = data["thresholds"], data["weights"]
    return TriageConfig(
        id=data["id"],
        version=int(data["version"]),
        sha256=sha,
        margin_threshold=float(th["margin"]),
        tj_proximity_c=float(th["tj_proximity_c"]),
        mode_boundary=float(th.get("mode_boundary", 0.20)),
        w1_margin=float(w["w1_margin"]),
        w2_thermal=float(w["w2_thermal"]),
        w3_lifetime=float(w["w3_lifetime"]),
        w4_blind_spot=float(w["w4_blind_spot"]),
        no_data=float(w.get("no_data", 1.0)),
        blind_spots=[
            BlindSpot(
                id=b["id"],
                topologies=tuple(b["topologies"]),
                roles=tuple(b["roles"]),
                param=b["param"],
                stat=b["stat"],
                scenario=b["scenario"],
                weight=float(b["weight"]),
                reason=b["reason"],
                how=b["how"],
                source=b["source"],
            )
            for b in data["blind_spots"]
        ],
        description=data.get("description", ""),
        source=data.get("source", ""),
        diagnostics=diags,
    )


def validate(data: Any, path: Path | None = None) -> list[Diagnostic]:
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    diags: list[Diagnostic] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        diags.append(_err(f"{where}: {err.message}", _line_of(path, err.absolute_path)))
    ids = [b.get("id") for b in (data or {}).get("blind_spots", []) if isinstance(b, dict)]
    for dup in {i for i in ids if ids.count(i) > 1}:
        diags.append(_err(f"duplicate blind-spot id {dup!r}"))
    return diags


def _line_of(path: Path | None, json_path: Any) -> int | None:
    """Best-effort line: the n-th '- ' list entry for blind_spots/<n>/..."""
    if path is None:
        return None
    parts = list(json_path)
    if len(parts) >= 2 and parts[0] == "blind_spots" and isinstance(parts[1], int):
        n = -1
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("- "):
                n += 1
                if n == parts[1]:
                    return lineno
    return None


def _err(message: str, line_no: int | None = None) -> Diagnostic:
    return Diagnostic(
        code="TRIAGE_CONFIG_INVALID",
        severity=Severity.ERROR,
        message=message,
        module=MODULE_ID,
        line_no=line_no,
    )
