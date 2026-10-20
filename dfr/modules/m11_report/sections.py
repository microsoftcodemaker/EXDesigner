"""Built-in report sections (PRD 3.11). Each is a ReportSectionSpec whose render returns an HTML
fragment from a RunBundle. Every stress/limit/Tj number goes through ``num()`` so it carries a
tier badge and a source tag (RPT-02). Other modules can add sections via REPORT_SECTIONS.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape
from typing import Any

from dfr.core.contracts import (
    AnalysisRun,
    DeratingResult,
    DeratingStatus,
    Diagnostic,
    Part,
    StressValue,
    ThermalResult,
)
from dfr.core.extension import ReportSectionSpec
from dfr.core.report import SOURCE_LABELS, num, table

_table = table
STATUS_ORDER = {
    DeratingStatus.FAIL: 0,
    DeratingStatus.WARN: 1,
    DeratingStatus.UNKNOWN: 2,
    DeratingStatus.PASS: 3,
}


@dataclass
class RunBundle:
    """Everything a section may need, loaded once per report."""

    run: AnalysisRun
    parts: dict[int, Part]
    stress_by_id: dict[int, StressValue]
    effective: dict[Any, StressValue]
    derating: list[DeratingResult]
    thermal: list[ThermalResult]
    diagnostics: list[Diagnostic]
    ruleset_id: str
    parent: RunBundle | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def refdes(self, part_id: int) -> str:
        p = self.parts.get(part_id)
        return p.refdes if p else f"part {part_id}"

    def tier_source_for(self, ids: tuple[int, ...]) -> tuple[int, str]:
        rows = [self.stress_by_id[i] for i in ids if i in self.stress_by_id]
        if not rows:
            return 1, "equation"
        worst = max(rows, key=lambda v: int(v.tier))
        return int(worst.tier), worst.source.value


def _status(s: DeratingStatus) -> str:
    return f'<span class="status {s.value}">{s.value.upper()}</span>'


# ----------------------------------------------------------------------------- sections


def render_summary(b: RunBundle) -> str:
    counts = {s: sum(r.status is s for r in b.derating) for s in STATUS_ORDER}
    t1 = sum(int(v.tier) == 1 for v in b.effective.values())
    t2 = sum(int(v.tier) == 2 for v in b.effective.values())
    total = t1 + t2
    mix = f"{t1} T1, {t2} T2 ({(100 * t2 // total) if total else 0} % Tier 2)"
    top = sorted(
        [r for r in b.derating if r.status in (DeratingStatus.FAIL, DeratingStatus.WARN)],
        key=lambda r: (STATUS_ORDER[r.status], r.margin if r.margin is not None else 0),
    )[:10]
    rows = [
        [
            escape(b.refdes(r.part_id)),
            escape(r.param),
            _status(r.status),
            f"{r.margin * 100:.1f} %" if r.margin is not None else "—",
            escape(r.rule_id),
        ]
        for r in top
    ]
    models = ", ".join(f"{k}@{v}" for k, v in sorted(b.run.model_set.items()))
    html = (
        f"<p>Run #{b.run.id} ({b.run.status.value}) · rule set <code>{escape(b.ruleset_id)}</code>"
        f" · models: {escape(models)}</p>"
        f"<p><strong>{counts[DeratingStatus.FAIL]} FAIL</strong>, "
        f"{counts[DeratingStatus.WARN]} WARN, "
        f"{counts[DeratingStatus.UNKNOWN]} UNKNOWN (missing rating, never PASS), "
        f"{counts[DeratingStatus.PASS]} PASS. "
        f"Fidelity mix: {mix}.</p>"
    )
    if rows:
        html += "<h3>Top risks</h3>" + _table(
            ["Part", "Parameter", "Status", "Margin", "Rule"], rows
        )
    return html


def render_methods(b: RunBundle) -> str:
    items = [
        "Tier 1 stress: ideal steady-state CCM equations per topology template (PRD 3.2).",
        "Derating: limit = factor * rating (+ offset); PASS <= limit, WARN <= rating, "
        "FAIL > rating; "
        "missing rating → UNKNOWN. Factors in the shipped rule set are marked <em>verify</em>.",
        "Thermal: Tj = Ta + P * theta with Rds_on(Tj) fixed-point iteration; "
        "no theta -> no Tj, never a guess.",
        "Equal current sharing is assumed for parallel capacitors (flagged).",
        "Not captured by Tier 1: switch-node ringing, start-up/inrush, load steps, "
        "DCM transitions, "
        "light-load modes, ESR/ESL current split, body-diode dead time (PRD 9.2).",
    ]
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def render_ranked(b: RunBundle) -> str:
    rows = []
    tj_by_part: dict[int, float] = {}
    for t in b.thermal:
        tj_by_part[t.part_id] = max(tj_by_part.get(t.part_id, float("-inf")), t.tj)
    for r in sorted(
        b.derating, key=lambda r: (STATUS_ORDER[r.status], r.margin if r.margin is not None else 0)
    ):
        tier, source = b.tier_source_for(r.stress_value_ids)
        tj = tj_by_part.get(r.part_id)
        rows.append(
            [
                escape(b.refdes(r.part_id)),
                escape(r.param),
                num(r.stress, tier, source),
                f"{r.limit:.4g}" if r.limit is not None else "—",
                f"{r.rating:.4g}" if r.rating is not None else "—",
                f"{r.margin * 100:.1f} %" if r.margin is not None else "—",
                _status(r.status),
                num(tj, tier, "equation", "{:.0f} °C") if tj is not None else "—",
                escape(r.rule_id),
            ]
        )
    return _table(
        ["Part", "Parameter", "Stress", "Limit", "Rating", "Margin", "Status", "Tj", "Rule"],
        rows,
        ["", "", "num", "num", "num", "num", "", "num", ""],
    )


def render_per_part(b: RunBundle) -> str:
    html = []
    by_part: dict[int, list[StressValue]] = {}
    for v in b.effective.values():
        by_part.setdefault(v.part_id, []).append(v)
    for pid in sorted(by_part, key=b.refdes):
        part = b.parts.get(pid)
        title = f"{b.refdes(pid)}" + (
            f" — {part.part_class.value}/{part.subtype or '-'}, {part.mpn or ''}" if part else ""
        )
        rows = [
            [
                escape(v.param),
                escape(v.scenario),
                num(v.value, int(v.tier), v.source.value),
                escape(v.unit),
                escape(v.stat.value),
                escape(v.tool),
                v.timestamp.strftime("%Y-%m-%d %H:%M"),
                escape(v.note or ""),
            ]
            for v in sorted(by_part[pid], key=lambda v: (v.param, v.scenario))
        ]
        html.append(
            f"<h3>{escape(title)}</h3>"
            + _table(
                ["Parameter", "Scenario", "Value", "Unit", "Stat", "Tool", "Timestamp", "Note"],
                rows,
                ["", "", "num", "", "", "", "", ""],
            )
        )
    return "".join(html) or "<p class='muted'>No stress values.</p>"


def render_refinement(b: RunBundle) -> str:
    if b.parent is None:
        return "<p class='muted'>Single run; no refinement chain.</p>"
    before = {(r.part_id, r.rule_id): r for r in b.parent.derating}
    rows = []
    for r in b.derating:
        p = before.get((r.part_id, r.rule_id))
        if p is None or (p.stress == r.stress and p.status is r.status):
            continue
        t_before, s_before = b.parent.tier_source_for(p.stress_value_ids)
        t_after, s_after = b.tier_source_for(r.stress_value_ids)
        rows.append(
            [
                escape(b.refdes(r.part_id)),
                escape(r.param),
                num(p.stress, t_before, s_before),
                num(r.stress, t_after, s_after),
                f"{p.margin * 100:.1f} % → {r.margin * 100:.1f} %"
                if p.margin is not None and r.margin is not None
                else "—",
                f"{_status(p.status)} → {_status(r.status)}",
            ]
        )
    intro = f"<p>Run #{b.run.id} refines run #{b.parent.run.id}.</p>"
    return intro + (
        _table(["Part", "Parameter", "Before", "After", "Margin", "Status"], rows)
        if rows
        else "<p class='muted'>No changed rows.</p>"
    )


def render_diagnostics(b: RunBundle) -> str:
    rows = [
        [
            escape(d.severity.value.upper()),
            escape(d.module or ""),
            escape(d.code),
            escape(d.message),
        ]
        for d in b.diagnostics
    ]
    return (
        _table(["Severity", "Module", "Code", "Message"], rows)
        if rows
        else "<p class='muted'>None.</p>"
    )


RenderFn = Callable[[RunBundle], str]

SECTIONS: list[tuple[ReportSectionSpec, RenderFn]] = [
    (ReportSectionSpec(id="summary", title="Executive summary", order=10), render_summary),
    (
        ReportSectionSpec(
            id="methods", title="Method, assumptions and Tier 1 limitations", order=20
        ),
        render_methods,
    ),
    (
        ReportSectionSpec(
            id="ranked", title="Ranked risk list (derating)", order=30, requires=("m5_derating",)
        ),
        render_ranked,
    ),
    (ReportSectionSpec(id="per_part", title="Per-part stress values", order=40), render_per_part),
    (
        ReportSectionSpec(id="refinement", title="Refinement: before / after", order=50),
        render_refinement,
    ),
    (
        ReportSectionSpec(id="diagnostics", title="Appendix: diagnostics", order=90),
        render_diagnostics,
    ),
]

__all__ = ["SECTIONS", "SOURCE_LABELS", "RunBundle", "num"]
