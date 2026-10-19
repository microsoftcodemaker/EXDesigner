"""Rule-set loading and JSON-Schema validation with line-numbered errors (DER-02, DER-05)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from dfr.core.contracts import Diagnostic, Severity

MODULE_ID = "m5_derating"
REPO_DATA = Path(os.environ.get("DFR_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
RULESETS_DIR = REPO_DATA / "rulesets"
SCHEMA_PATH = REPO_DATA / "schemas" / "ruleset.schema.json"


@dataclass(frozen=True)
class Rule:
    id: str
    part_class: str
    subtype: str | None
    param: str
    rating: str
    factor: float
    offset: float
    curve: tuple[str, str] | None  # (t_knee rating name, t_max rating name)
    source: str
    verify: bool


@dataclass
class RuleSet:
    id: str
    version: int
    rules: list[Rule]
    sha256: str
    description: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def for_part(self, part_class: str, subtype: str | None) -> list[Rule]:
        """Subtype-specific rules first; a generic (subtype None) rule applies only when no
        subtype rule covers the same param."""
        specific = [
            r
            for r in self.rules
            if r.part_class == part_class and r.subtype is not None and r.subtype == subtype
        ]
        covered = {r.param for r in specific}
        generic = [
            r
            for r in self.rules
            if r.part_class == part_class and r.subtype is None and r.param not in covered
        ]
        return [*specific, *generic]


def load_ruleset(ruleset_id: str, *, directory: Path = RULESETS_DIR) -> RuleSet | None:
    path = directory / f"{ruleset_id}.yaml"
    if not path.is_file():
        return None
    return load_ruleset_file(path)


def load_ruleset_file(path: Path) -> RuleSet:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        return RuleSet(
            path.stem,
            0,
            [],
            sha,
            diagnostics=[_err(f"YAML error: {exc}", getattr(mark, "line", None))],
        )
    diags = validate(data, path)
    if any(d.severity is Severity.ERROR for d in diags):
        return RuleSet(path.stem, 0, [], sha, diagnostics=diags)
    rules = [
        Rule(
            id=r["id"],
            part_class=r["part_class"],
            subtype=r.get("subtype"),
            param=r["param"],
            rating=r["rating"],
            factor=float(r["factor"]),
            offset=float(r.get("offset", 0.0)),
            curve=(r["curve"]["t_knee"], r["curve"]["t_max"]) if r.get("curve") else None,
            source=r["source"],
            verify=bool(r.get("verify", True)),
        )
        for r in data["rules"]
    ]
    return RuleSet(data["id"], int(data["version"]), rules, sha, data.get("description", ""), diags)


def validate(data: Any, path: Path | None = None) -> list[Diagnostic]:
    schema = _schema()
    validator = jsonschema.Draft202012Validator(schema)
    diags: list[Diagnostic] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        diags.append(_err(f"{where}: {err.message}", _line_of(path, err.absolute_path)))
    ids = [r.get("id") for r in (data or {}).get("rules", []) if isinstance(r, dict)]
    for dup in {i for i in ids if ids.count(i) > 1}:
        diags.append(_err(f"duplicate rule id {dup!r}"))
    return diags


def _schema() -> dict[str, Any]:
    import json  # noqa: PLC0415

    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _line_of(path: Path | None, json_path: Any) -> int | None:
    """Best-effort line number: the n-th '- {' rule entry for rules/<n>/..."""
    if path is None:
        return None
    parts = list(json_path)
    if len(parts) >= 2 and parts[0] == "rules" and isinstance(parts[1], int):
        n = -1
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("- "):
                n += 1
                if n == parts[1]:
                    return lineno
    return None


def _err(message: str, line_no: int | None = None) -> Diagnostic:
    return Diagnostic(
        code="RULESET_INVALID",
        severity=Severity.ERROR,
        message=message,
        module=MODULE_ID,
        line_no=line_no,
    )
