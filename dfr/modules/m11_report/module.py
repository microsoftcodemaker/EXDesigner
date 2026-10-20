"""M11: reporting (PRD 3.11). Builds a self-contained HTML report from stored runs.

PDF rendering (QtWebEngine printToPdf) lives in the UI layer; this module is Qt-free.
Result rows of other modules are read through their services (``load_derating_results``,
``load_thermal_results``) so M11 imports no module package. Any module can add rows for its own
sections with a ``report.bundle_extras(session, run_id) -> dict`` service (merged into
``RunBundle.extras``) and sections with a ``report.sections() -> [(spec, render)]`` service.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from dfr import __version__
from dfr.api import API_VERSION, ModuleSpec
from dfr.core.db.repos import DesignRepo, DiagnosticRepo, PartRepo, RunRepo, StressRepo
from dfr.core.ports import Clock, SystemClock
from dfr.modules.m11_report.sections import SECTIONS, SOURCE_LABELS, RunBundle

MODULE_ID = "m11_report"
VERSION = "0.1.0"
TEMPLATES = Path(__file__).parent / "templates"


def load_bundle(
    session: Session, registry: Any, run_id: int, clock: Clock | None = None, *, depth: int = 1
) -> RunBundle:
    clock = clock or SystemClock()
    runs = RunRepo(session, clock)
    run = runs.get(run_id)
    if run is None:
        msg = f"run {run_id} not found"
        raise LookupError(msg)
    parts = {
        p.id: p for p in PartRepo(session).for_version(run.design_version_id) if p.id is not None
    }
    stress = StressRepo(session, clock)
    all_values = {v.id: v for v in stress.for_version(run.design_version_id) if v.id is not None}
    eff_ids = runs.effective_ids(run_id)
    effective = {k: all_values[i] for k, i in eff_ids.items() if i in all_values}
    derating = (
        registry.service("load_derating_results")(session, run_id)
        if registry.has_service("load_derating_results")
        else []
    )
    thermal = (
        registry.service("load_thermal_results")(session, run_id)
        if registry.has_service("load_thermal_results")
        else []
    )
    parent = None
    if run.parent_run_id is not None and depth > 0:
        parent = load_bundle(session, registry, run.parent_run_id, clock, depth=depth - 1)
    extras: dict[str, Any] = {}
    for provider in registry.services_named("report.bundle_extras"):
        extras.update(provider(session, run_id))
    return RunBundle(
        run=run,
        parts=parts,
        stress_by_id=all_values,
        effective=effective,
        derating=derating,
        thermal=thermal,
        diagnostics=DiagnosticRepo(session).for_run(run_id),
        ruleset_id=run.ruleset_id,
        parent=parent,
        extras=extras,
    )


def build_report_html(
    session: Session,
    registry: Any,
    run_id: int,
    *,
    clock: Clock | None = None,
    section_ids: list[str] | None = None,
) -> str:
    bundle = load_bundle(session, registry, run_id, clock)
    design_name = _design_name(session, bundle, clock or SystemClock())
    present = {m.id for m in registry.modules}
    sections = []
    extra = []
    for provider in registry.services_named("report.sections"):
        extra.extend(provider())
    for spec, render in [*SECTIONS, *extra]:
        if section_ids is not None and spec.id not in section_ids:
            continue
        if not set(spec.requires) <= present:
            continue
        sections.append(
            {"id": spec.id, "title": spec.title, "order": spec.order, "html": render(bundle)}
        )
    sections.sort(key=lambda s: s["order"])
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    return env.get_template("report.html.j2").render(
        cover={
            "design_name": design_name,
            "generated_at": (clock or SystemClock())
            .now()
            .astimezone(UTC)
            .strftime("%Y-%m-%d %H:%M UTC"),
            "tool_version": __version__,
        },
        sections=sections,
        source_labels=SOURCE_LABELS,
    )


def write_report_html(
    session: Session, registry: Any, run_id: int, out: Path, *, clock: Clock | None = None
) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report_html(session, registry, run_id, clock=clock), encoding="utf-8")
    return out


def _design_name(session: Session, bundle: RunBundle, clock: Clock) -> str:
    repo = DesignRepo(session, clock)
    for d in repo.list_all():
        if any(v.id == bundle.run.design_version_id for v in repo.versions(d.id)):
            return d.name
    return f"design version {bundle.run.design_version_id}"


MODULE = ModuleSpec(
    id=MODULE_ID,
    name="Reporting",
    version=VERSION,
    api_version=API_VERSION,
    optional=True,
    services={
        "build_report_html": build_report_html,
        "write_report_html": write_report_html,
        "load_report_bundle": load_bundle,
    },
)

__all__ = ["MODULE", "build_report_html", "load_bundle", "write_report_html"]
