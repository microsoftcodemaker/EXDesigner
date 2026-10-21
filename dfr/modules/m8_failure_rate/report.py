"""M8 report section: per-method system figures, top contributors, exclusions and the PRD 3.8
model-comparison table (MTB-05). Numbers go through ``num()`` (RPT-02); failure-rate figures carry
no stress tier, so they are badged T1/equation unless a per-part factor used a T2 stress value.
"""

from __future__ import annotations

from html import escape
from typing import Any

from dfr.api import ReportSectionSpec, muted, num, table
from dfr.core.contracts import FailureRateResult
from dfr.modules.m8_failure_rate.tables import MODULE_ID

SPEC = ReportSectionSpec(
    id="failure_rate", title="Failure rate and MTBF", order=37, requires=(MODULE_ID,)
)
HOURS_PER_YEAR = 8766.0
COMPARISON_HEADER = ["Aspect", "MIL-HDBK-217F", "Telcordia SR-332", "Physics-of-failure"]

COMPARISON = [
    ["Failure-rate shape", "Constant", "Constant (with data updates)", "Wear-out (increasing)"],
    [
        "Data basis",
        "Legacy military field data",
        "Telecom field data",
        "Mechanism models, test data",
    ],
    [
        "Stress inputs",
        "Temperature, electrical stress, quality, environment",
        "Temperature, electrical stress, quality",
        "Actual stress and temperature cycles",
    ],
    [
        "Strengths",
        "Free, widely cited, simple",
        "More current than 217F, supports data updates",
        "Reflects real design weak points",
    ],
    [
        "Limits",
        "Dated, pessimistic, ignores wear-out",
        "Licensed, parameter tables required",
        "Needs model constants per part; fewer parts covered",
    ],
    [
        "Best use",
        "Quick comparison, legacy requirements",
        "Commercial telecom-style estimates",
        "Design-weakness identification",
    ],
]


def render_failure_rate(b: Any) -> str:
    results: list[FailureRateResult] = list(b.extras.get("failure_rate", []))
    if not results:
        return muted("No failure-rate results (no table found).")
    html = []
    for r in results:
        html.append(_one(b, r))
    html.append(
        "<h3>Model comparison (PRD 3.8)</h3>"
        + table(
            COMPARISON_HEADER,
            [[escape(c) for c in row] for row in COMPARISON],
        )
    )
    return "".join(html)


def _one(b: Any, r: FailureRateResult) -> str:
    conf = r.confidence.value if r.confidence else "n/a"
    head = f"<h3>{escape(r.method)} (confidence {escape(conf)})</h3>"
    if r.system_lambda_fit is not None and r.system_mtbf_h is not None:
        figures = (
            f"<p>System λ {num(r.system_lambda_fit, 1, 'equation', '{:.1f} FIT')} · MTBF "
            f"{num(r.system_mtbf_h / HOURS_PER_YEAR, 1, 'equation', '{:.1f} y')} "
            f"(series, constant rate).</p>"
        )
    elif r.system_mttf_h is not None:
        b10 = (
            num(r.b10_h / HOURS_PER_YEAR, 1, "equation", "{:.1f} y") if r.b10_h is not None else "—"
        )
        figures = (
            f"<p>MTTF {num(r.system_mttf_h / HOURS_PER_YEAR, 1, 'equation', '{:.1f} y')} · "
            f"B10 {b10} (wear-out roll-up; MTBF not shown for non-constant rates).</p>"
        )
    else:
        figures = "<p><strong>Not available</strong>: no part could be rated.</p>"
    rows = []
    for p in r.per_part[:15]:
        factors = ", ".join(f"{k}={v:.3g}" for k, v in p.factors.items())
        rows.append(
            [
                escape(b.refdes(p.part_id)),
                num(p.lambda_fit, 1, "equation", "{:.2f} FIT"),
                escape(factors),
            ]
        )
    body = table(["Part", "λ (FIT)", "Factors"], rows, ["", "num", ""]) if rows else ""
    excl = ""
    if r.excluded_reasons:
        excl = "<h4>Excluded parts</h4>" + table(
            ["Part", "Why"],
            [
                [escape(b.refdes(pid)), escape(why)]
                for pid, why in sorted(r.excluded_reasons.items(), key=lambda kv: b.refdes(kv[0]))
            ],
        )
    assumptions = "<ul>" + "".join(f"<li>{escape(a)}</li>" for a in r.assumptions) + "</ul>"
    return head + figures + body + excl + assumptions


def comparison() -> tuple[list[str], list[list[str]]]:
    """PRD 3.8 model-comparison table for the in-app panel (MTB-05)."""
    return list(COMPARISON_HEADER), [list(r) for r in COMPARISON]


def sections() -> list[tuple[ReportSectionSpec, Any]]:
    return [(SPEC, render_failure_rate)]
