"""M7 report section: lifetime estimates with source and confidence (PRD 3.7 "Output", RPT-02).

Rows come from ``RunBundle.extras["lifetime"]`` (loaded by this module's ``report.bundle_extras``
service). Every life number goes through ``num()``; the tier/source badge is that of the stress
values the model consumed (``input_stress_ids``), T1/equation when it used none.
"""

from __future__ import annotations

from html import escape
from typing import Any

from dfr.api import ReportSectionSpec, muted, num, table
from dfr.core.contracts import LifetimeResult
from dfr.modules.m7_lifetime.constants import HOURS_PER_YEAR, MODULE_ID

SPEC = ReportSectionSpec(
    id="lifetime", title="Lifetime estimates (wear-out)", order=35, requires=(MODULE_ID,)
)


def render_lifetime(b: Any) -> str:
    rows_in: list[LifetimeResult] = list(b.extras.get("lifetime", []))
    if not rows_in:
        return muted("No lifetime rows: no part matched a wear-out model.")
    target_h = _target_hours(b)
    estimated = [r for r in rows_in if r.life_hours is not None]
    na = [r for r in rows_in if r.life_hours is None]
    rows = []
    for r in sorted(
        estimated, key=lambda r: (r.life_hours if r.life_hours is not None else 0.0, r.part_id)
    ):
        tier, source = b.tier_source_for(tuple(r.input_stress_ids))
        years = (r.life_hours or 0.0) / HOURS_PER_YEAR
        verdict = (
            "—"
            if target_h is None
            else ("<strong>below target</strong>" if (r.life_hours or 0.0) < target_h else "ok")
        )
        rows.append(
            [
                escape(b.refdes(r.part_id)),
                escape(r.mechanism),
                num(years, tier, source, "{:.1f} y"),
                verdict,
                escape(r.confidence.value),
                escape(r.model_id),
                "<br>".join(escape(a) for a in r.assumptions),
            ]
        )
    html = (
        f"<p>{len(estimated)} estimate(s), {len(na)} not available (missing vendor data, never "
        "guessed). Confidence is <em>low</em> whenever a seed constant marked <em>verify</em> "
        "decided the number; the source of every constant is listed in the assumptions.</p>"
    )
    if rows:
        html += table(
            ["Part", "Mechanism", "Life", "vs target", "Confidence", "Model", "Assumptions"],
            rows,
            ["", "", "num", "", "", "", ""],
        )
    if na:
        html += "<h3>Not available</h3>" + table(
            ["Part", "Mechanism", "Model", "Why"],
            [
                [
                    escape(b.refdes(r.part_id)),
                    escape(r.mechanism),
                    escape(r.model_id),
                    escape(r.assumptions[0] if r.assumptions else "no data"),
                ]
                for r in sorted(na, key=lambda r: (b.refdes(r.part_id), r.model_id))
            ],
        )
    return html


def _target_hours(b: Any) -> float | None:
    profile = b.extras.get("mission_profile")
    return float(profile.target_life_hours) if profile is not None else None


def sections() -> list[tuple[ReportSectionSpec, Any]]:
    return [(SPEC, render_lifetime)]
