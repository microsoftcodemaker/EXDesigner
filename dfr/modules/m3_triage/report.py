"""M3 report section: the ranked refinement list with waivers and their reasons (TRI-03).

Rows come from ``RunBundle.extras["refinement"]`` (this module's ``report.bundle_extras``
service). The score is a dimensionless rank computed from the part's effective stress values, so
it is badged with the worst tier among them (RPT-02).
"""

from __future__ import annotations

from html import escape
from typing import Any

from dfr.api import ReportSectionSpec, muted, num, table
from dfr.core.contracts import RefinementItem
from dfr.modules.m3_triage.config import MODULE_ID

SPEC = ReportSectionSpec(
    id="triage", title="Risk triage and refinement plan", order=32, requires=(MODULE_ID,)
)


def render_triage(b: Any) -> str:
    items: list[RefinementItem] = list(b.extras.get("refinement", []))
    if not items:
        return muted("No triage rows: nothing flagged.")
    open_items = [i for i in items if i.status != "waived"]
    waived = [i for i in items if i.status == "waived"]
    html = (
        f"<p>{len(open_items)} open item(s), {len(waived)} waived. Score = w1·margin + w2·thermal "
        "headroom + w3·lifetime shortfall + w4·blind spot (PRD 3.3); missing data scores as a "
        "flag, never as a pass.</p>"
    )
    if open_items:
        html += table(
            ["Rank", "Part", "Score", "Flags", "Reasons", "Refine", "Scenarios"],
            [_row(b, rank, it) for rank, it in enumerate(open_items, 1)],
            ["num", "", "num", "", "", "", ""],
        )
    if waived:
        html += "<h3>Waived (kept for the record)</h3>" + table(
            ["Part", "Flags", "Reasons", "Waiver reason"],
            [
                [
                    escape(b.refdes(it.part_id)),
                    escape(", ".join(it.flags)),
                    "<br>".join(escape(r) for r in it.reasons),
                    escape(it.waiver_reason or ""),
                ]
                for it in waived
            ],
        )
    return html


def _row(b: Any, rank: int, it: RefinementItem) -> list[str]:
    tier, source = _part_tier(b, it.part_id)
    return [
        str(rank),
        escape(b.refdes(it.part_id)),
        num(it.score, tier, source, "{:.3f}"),
        escape(", ".join(it.flags)),
        "<br>".join(escape(r) for r in it.reasons),
        escape(", ".join(it.parameters_to_refine)),
        escape(", ".join(it.recommended_scenarios)),
    ]


def _part_tier(b: Any, part_id: int) -> tuple[int, str]:
    ids = tuple(v.id for v in b.effective.values() if v.part_id == part_id and v.id is not None)
    tier, source = b.tier_source_for(ids)
    return int(tier), str(source)


def sections() -> list[tuple[ReportSectionSpec, Any]]:
    return [(SPEC, render_triage)]
