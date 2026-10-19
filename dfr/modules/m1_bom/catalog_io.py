"""Catalog import / export: JSON (schema-validated) and flat CSV, organised in datasets.

- Import of a dataset name that already exists replaces that dataset's rows (re-import).
- One row per MPN across datasets: a later import merges into it and takes ownership, so
  deleting a dataset removes the entries it last wrote.
- A dataset can be deleted as a unit; rows written through the UI live in dataset ``user``.
- Every rating keeps its ``source`` text as ``provenance_ref`` with provenance ``catalog``.
- Nothing is fetched from the network; files come from the user.

Format reference: docs/catalog_format.md. Schema: data/schemas/catalog.schema.json.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from sqlalchemy.orm import Session

from dfr.core.contracts import Diagnostic, PartClass, Rating, RatingProvenance, Severity
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.ports import Clock
from dfr.core.units import UnitError, validate_unit
from dfr.modules.m1_bom.catalog import CatalogRepo, PartCatalogRow

MODULE_ID = "m1_bom"
DATA_DIR = Path(os.environ.get("DFR_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
SCHEMA_PATH = DATA_DIR / "schemas" / "catalog.schema.json"
CSV_COLUMNS = (
    "mpn",
    "libref",
    "footprint",
    "class",
    "subtype",
    "rating",
    "value",
    "unit",
    "source",
    "pin",
    "function",
)
USER_DATASET = "user"


@dataclass
class CatalogEntry:
    key: str  # MPN, or "libref@footprint"
    part_class: PartClass
    subtype: str | None = None
    mpn: str | None = None
    libref: str | None = None
    footprint: str | None = None
    ratings: dict[str, Rating] = field(default_factory=dict)
    pinmap: dict[str, str] = field(default_factory=dict)
    note: str = ""


@dataclass
class CatalogFile:
    dataset: str
    entries: list[CatalogEntry]
    fmt: str
    sha256: str
    description: str = ""
    verify: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(d.severity is Severity.ERROR for d in self.diagnostics)


@dataclass(frozen=True)
class ImportSummary:
    dataset: str
    entries: int
    ratings: int
    pins: int
    replaced: bool
    diagnostics: list[Diagnostic]


# ----------------------------------------------------------------------------- parse


def parse_catalog(data: bytes, name: str, *, dataset: str | None = None) -> CatalogFile:
    """Detect JSON vs CSV by content, validate, and return entries (never raises)."""
    text = data.decode("utf-8-sig", errors="replace")
    sha = hashlib.sha256(data).hexdigest()
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return _parse_json(text, name, sha, dataset)
    return _parse_csv(text, name, sha, dataset or Path(name).stem)


def _parse_json(text: str, name: str, sha: str, dataset: str | None) -> CatalogFile:
    sink = DiagnosticSink(MODULE_ID)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        sink.error("CATALOG_JSON_INVALID", f"{name}: {exc.msg}", line_no=exc.lineno)
        return CatalogFile(
            dataset or Path(name).stem, [], "json", sha, diagnostics=list(sink.items)
        )
    validator = jsonschema.Draft202012Validator(_schema())
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        sink.error("CATALOG_SCHEMA", f"{name}: {where}: {err.message}")
    if sink.has_errors:
        return CatalogFile(
            dataset or str(doc.get("dataset", Path(name).stem)),
            [],
            "json",
            sha,
            diagnostics=list(sink.items),
        )
    file_verify = bool(doc.get("verify", False))
    entries = [
        e
        for key, spec in doc["parts"].items()
        if (e := _entry_from_json(key, spec, file_verify, sink)) is not None
    ]
    return CatalogFile(
        dataset=dataset or str(doc["dataset"]),
        entries=entries,
        fmt="json",
        sha256=sha,
        description=str(doc.get("description", "")),
        verify=file_verify,
        diagnostics=list(sink.items),
    )


def _entry_from_json(
    key: str, spec: dict[str, Any], file_verify: bool, sink: DiagnosticSink
) -> CatalogEntry | None:
    ratings: dict[str, Rating] = {}
    for rname, r in (spec.get("ratings") or {}).items():
        unit = str(r["unit"])
        if unit:
            try:
                validate_unit(unit)
            except UnitError:
                sink.error("CATALOG_UNIT", f"{key}.{rname}: unknown unit {unit!r}")
                continue
        source = str(r["source"])
        if r.get("verify", file_verify):
            source = f"{source} (verify)"
        ratings[rname] = Rating(
            name=rname,
            value=float(r["value"]),
            unit=unit,
            provenance=RatingProvenance.CATALOG,
            provenance_ref=source,
        )
    libref, footprint = spec.get("libref"), spec.get("footprint")
    mpn: str | None = key
    if "@" in key and not spec.get("mpn"):
        # "LIBREF@FOOTPRINT" keys describe symbol-based entries without an MPN.
        mpn = None
        lr, _, fp = key.partition("@")
        libref, footprint = libref or lr, footprint or fp
    return CatalogEntry(
        key=key,
        part_class=PartClass(spec["class"]),
        subtype=spec.get("subtype"),
        mpn=mpn,
        libref=libref,
        footprint=footprint,
        ratings=ratings,
        pinmap={str(k): str(v) for k, v in (spec.get("pinmap") or {}).items()},
        note=str(spec.get("note", "")),
    )


def _parse_csv(text: str, name: str, sha: str, dataset: str) -> CatalogFile:
    """Flat CSV: one row per rating or per pin (see docs). Delimiter sniffed (',' or ';')."""
    sink = DiagnosticSink(MODULE_ID)
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = {"mpn", "class"} - set(headers)
    if missing or not ({"rating", "pin"} & set(headers)):
        sink.error(
            "CATALOG_CSV_HEADER",
            f"{name}: need columns mpn, class and rating/value/unit/source or pin/function; "
            f"got {headers}",
        )
        return CatalogFile(dataset, [], "csv", sha, diagnostics=list(sink.items))
    entries: dict[str, CatalogEntry] = {}
    for line_no, raw in enumerate(reader, 2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        key = row.get("mpn") or (
            f"{row.get('libref')}@{row.get('footprint')}" if row.get("libref") else ""
        )
        if not key:
            sink.error("CATALOG_CSV_ROW", f"{name}: row without mpn or libref", line_no=line_no)
            continue
        try:
            cls = PartClass(row.get("class", ""))
        except ValueError:
            sink.error(
                "CATALOG_CSV_ROW", f"{name}: unknown class {row.get('class')!r}", line_no=line_no
            )
            continue
        entry = entries.setdefault(
            key,
            CatalogEntry(
                key=key,
                part_class=cls,
                subtype=row.get("subtype") or None,
                mpn=row.get("mpn") or None,
                libref=row.get("libref") or None,
                footprint=row.get("footprint") or None,
            ),
        )
        if row.get("rating"):
            try:
                value = float(row.get("value", ""))
            except ValueError:
                sink.error(
                    "CATALOG_CSV_ROW",
                    f"{name}: {key}.{row['rating']}: value {row.get('value')!r} is not a number",
                    line_no=line_no,
                )
                continue
            unit = row.get("unit", "")
            if unit:
                try:
                    validate_unit(unit)
                except UnitError:
                    sink.error(
                        "CATALOG_UNIT",
                        f"{name}: {key}.{row['rating']}: unknown unit {unit!r}",
                        line_no=line_no,
                    )
                    continue
            source = row.get("source") or ""
            if len(source) < 3:
                sink.error(
                    "CATALOG_CSV_ROW",
                    f"{name}: {key}.{row['rating']}: a source is required",
                    line_no=line_no,
                )
                continue
            entry.ratings[row["rating"]] = Rating(
                name=row["rating"],
                value=value,
                unit=unit,
                provenance=RatingProvenance.CATALOG,
                provenance_ref=source,
            )
        if row.get("pin") and row.get("function"):
            entry.pinmap[row["pin"]] = row["function"]
    return CatalogFile(dataset, list(entries.values()), "csv", sha, diagnostics=list(sink.items))


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# ----------------------------------------------------------------------------- import/export/delete


def import_catalog(
    session: Session, clock: Clock, parsed: CatalogFile, *, filename: str
) -> ImportSummary:
    """Replace the dataset's rows with the file's entries. Invalid files import nothing."""
    repo = CatalogRepo(session, clock)
    if not parsed.ok:
        return ImportSummary(parsed.dataset, 0, 0, 0, False, list(parsed.diagnostics))
    replaced = repo.delete_dataset(parsed.dataset) > 0
    n_ratings = n_pins = 0
    for e in parsed.entries:
        # One row per MPN: an existing entry from another dataset is merged (this file wins
        # per rating / per pin) and ownership moves to this dataset.
        existing = repo.find(mpn=e.mpn, libref=e.libref, footprint=e.footprint)
        ratings = {**repo.ratings_for(existing), **e.ratings} if existing else dict(e.ratings)
        pinmap = {**repo.pinmap_for(existing), **e.pinmap} if existing else dict(e.pinmap)
        repo.upsert(
            mpn=e.mpn,
            libref=e.libref,
            footprint=e.footprint,
            part_class=e.part_class,
            subtype=e.subtype,
            ratings=ratings,
            pinmap=pinmap or None,
            source="catalog",
            dataset=parsed.dataset,
        )
        n_ratings += len(e.ratings)
        n_pins += len(e.pinmap)
    repo.record_import(
        dataset=parsed.dataset,
        filename=filename,
        fmt=parsed.fmt,
        sha256=parsed.sha256,
        entries=len(parsed.entries),
        description=parsed.description,
    )
    session.flush()
    return ImportSummary(
        parsed.dataset, len(parsed.entries), n_ratings, n_pins, replaced, list(parsed.diagnostics)
    )


def export_catalog(session: Session, clock: Clock, *, dataset: str | None = None) -> str:
    """JSON in the import format, so a user can edit and re-import."""
    repo = CatalogRepo(session, clock)
    parts: dict[str, Any] = {}
    for row in repo.all_rows(dataset):
        key = row.mpn or f"{row.libref}@{row.footprint or ''}"
        ratings = {
            name: {
                "value": r.value,
                "unit": r.unit,
                "source": r.provenance_ref or r.provenance.value,
            }
            for name, r in repo.ratings_for(row).items()
        }
        spec: dict[str, Any] = {"class": row.part_class}
        if row.subtype:
            spec["subtype"] = row.subtype
        if row.libref and row.mpn:
            spec["libref"] = row.libref
        if row.footprint and row.mpn:
            spec["footprint"] = row.footprint
        if ratings:
            spec["ratings"] = ratings
        pinmap = repo.pinmap_for(row)
        if pinmap:
            spec["pinmap"] = pinmap
        parts[key] = spec
    doc = {
        "format_version": 1,
        "dataset": dataset or "export",
        "description": "exported by DfR Toolkit",
        "parts": parts,
    }
    return json.dumps(doc, indent=2, sort_keys=True)


def delete_dataset(session: Session, clock: Clock, dataset: str) -> int:
    n = CatalogRepo(session, clock).delete_dataset(dataset)
    session.flush()
    return n


def list_datasets(session: Session, clock: Clock) -> list[dict[str, Any]]:
    repo = CatalogRepo(session, clock)
    counts: dict[str, int] = {}
    for row in repo.all_rows():
        counts[row.dataset] = counts.get(row.dataset, 0) + 1
    out = [
        {
            "dataset": d.dataset,
            "filename": d.filename,
            "format": d.fmt,
            "entries": counts.get(d.dataset, 0),
            "imported_at": d.imported_at,
            "description": d.description,
            "sha256": d.sha256,
        }
        for d in repo.datasets()
    ]
    if counts.get(USER_DATASET):
        out.append(
            {
                "dataset": USER_DATASET,
                "filename": "(entered in the app)",
                "format": "ui",
                "entries": counts[USER_DATASET],
                "imported_at": None,
                "description": "ratings and pinouts edited in the UI",
                "sha256": "",
            }
        )
    return out


def catalog_rows(session: Session, clock: Clock) -> list[PartCatalogRow]:
    return CatalogRepo(session, clock).all_rows()
