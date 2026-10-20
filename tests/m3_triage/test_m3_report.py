"""M3 report section: ranked open items, waived items with reasons (TRI-03), badged scores."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dfr.core.contracts import RefinementItem
from dfr.modules.m3_triage.module import MODULE, bundle_extras
from dfr.modules.m3_triage.report import SPEC, render_triage, sections


@dataclass
class FakeValue:
    id: int
    part_id: int


@dataclass
class FakeBundle:
    extras: dict[str, Any] = field(default_factory=dict)
    effective: dict[Any, FakeValue] = field(default_factory=dict)
    tiers: dict[int, int] = field(default_factory=dict)

    def refdes(self, part_id: int) -> str:
        return f"P{part_id}"

    def tier_source_for(self, ids):
        rows = [self.tiers[i] for i in ids if i in self.tiers]
        return (max(rows), "measured") if rows else (1, "equation")


def _item(pid, score, status="open", **kw) -> RefinementItem:
    return RefinementItem(
        part_id=pid,
        flags=kw.get("flags", ["F1"]),
        reasons=kw.get("reasons", [f"P{pid}: margin 5 %"]),
        score=score,
        parameters_to_refine=kw.get("params", ["v_dc"]),
        recommended_scenarios=kw.get("scenarios", ["vin_max"]),
        status=status,
        waiver_reason=kw.get("waiver_reason"),
    )


def test_render_open_and_waived() -> None:
    b = FakeBundle(
        extras={
            "refinement": [
                _item(1, 1.2, flags=["F0", "F4:sw_vds_ringing"]),
                _item(2, 0.4),
                _item(3, 0.3, status="waived", waiver_reason="transient only <ok>"),
            ]
        },
        effective={"a": FakeValue(10, 1), "b": FakeValue(11, 2)},
        tiers={10: 1, 11: 2},
    )
    html = render_triage(b)
    values = re.findall(r'<span class="value">([^<]*)</span><span class="badge t(\d)">', html)
    assert values == [("1.200", "1"), ("0.400", "2")]  # waived rows carry no score
    assert "2 open item(s), 1 waived" in html
    assert "Waived (kept for the record)" in html and "transient only &lt;ok&gt;" in html
    assert "F0, F4:sw_vds_ringing" in html and '<td class="num">1</td>' in html
    assert "<p class='muted'>" in render_triage(FakeBundle())


def test_services_registered(session) -> None:
    assert MODULE.services["report.sections"] is sections
    assert sections()[0][0] is SPEC and SPEC.requires == ("m3_triage",)
    assert MODULE.services["report.bundle_extras"] is bundle_extras
    assert bundle_extras(session, 999) == {"refinement": []}
