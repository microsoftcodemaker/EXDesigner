"""M9 report section: FMEA table sorted by RPN (FME-03, PRD 3.9). S/O/D/RPN are ranks derived
from the part's data, so they carry the worst tier of the part's effective stress (RPT-02); the
O basis says whether it came from a rate, a life or no data."""

from __future__ import annotations

from html import escape
from typing import Any

from dfr.api import ReportSectionSpec, muted, num, table
from dfr.core.contracts import FmeaRow
from dfr.modules.m9_fmea.library import MODULE_ID

SPEC = ReportSectionSpec(id="fmea", title="FMEA (component level)", order=40, requires=(MODULE_ID,))
TOP_N = 40


def render_fmea(b: Any) -> str:
    rows: list[FmeaRow] = list(b.extras.get("fmea", []))
    if not rows:
        return muted("No FMEA rows.")
    no_data = sum(r.occurrence_basis == "no_data" for r in rows)
    user = sum("user" in r.source_flags.values() for r in rows)
    html = (
        f"<p>{len(rows)} rows (top {min(TOP_N, len(rows))} by RPN shown). RPN = S x O x D. "
        f"O from λ_mode = λ_part x mode fraction (M8) or life / target (M7, wear-out modes); "
        f"{no_data} row(s) have no rate or life and use O = 10 (conservative, not a guess). "
        f"{user} row(s) carry user overrides. Library defaults are seed values (verify).</p>"
    )
    body = []
    for r in rows[:TOP_N]:
        ids = tuple(
            v.id for v in b.effective.values() if v.part_id == r.part_id and v.id is not None
        )
        tier, source = b.tier_source_for(ids)
        flags = ", ".join(f"{k}:{v}" for k, v in sorted(r.source_flags.items()))
        body.append(
            [
                escape(b.refdes(r.part_id)),
                escape(r.mode),
                escape(r.system_effect),
                num(r.severity, tier, source, "{:.0f}"),
                num(r.occurrence, tier, source, "{:.0f}"),
                num(r.detection, tier, source, "{:.0f}"),
                num(r.rpn, tier, source, "{:.0f}"),
                escape(flags),
                escape(r.mitigation_note or ""),
            ]
        )
    return html + table(
        ["Part", "Mode", "System effect", "S", "O", "D", "RPN", "Basis", "Note"],
        body,
        ["", "", "", "num", "num", "num", "num", "", ""],
    )


def sections() -> list[tuple[ReportSectionSpec, Any]]:
    return [(SPEC, render_fmea)]
