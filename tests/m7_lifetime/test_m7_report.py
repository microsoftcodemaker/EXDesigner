"""M7 report section: life numbers badged, n/a rows listed with their reason, target verdict."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest

from dfr.core.contracts import (
    Confidence,
    ConverterSpec,
    LifetimeResult,
    MissionProfile,
    RunConfig,
)
from dfr.modules.m7_lifetime.module import MODULE, bundle_extras
from dfr.modules.m7_lifetime.report import SPEC, render_lifetime, sections


@dataclass
class FakeBundle:
    extras: dict[str, Any] = field(default_factory=dict)
    tiers: dict[int, int] = field(default_factory=dict)

    def refdes(self, part_id: int) -> str:
        return f"P{part_id}"

    def tier_source_for(self, ids):
        rows = [self.tiers[i] for i in ids if i in self.tiers]
        return (max(rows), "measured") if rows else (1, "equation")


def _lr(pid, life, **kw) -> LifetimeResult:
    return LifetimeResult(
        part_id=pid,
        mechanism=kw.get("mechanism", "electrolyte_dry_out"),
        model_id=kw.get("model_id", "cap_aluminum_electrolytic_temperature_rule"),
        life_hours=life,
        confidence=kw.get("confidence", Confidence.LOW),
        assumptions=kw.get("assumptions", ("PRD 3.7 (verify)",)),
        input_stress_ids=kw.get("ids", ()),
    )


def test_render_badges_and_na() -> None:
    b = FakeBundle(
        extras={
            "lifetime": [
                _lr(1, 8766 * 4.0, ids=(10,)),
                _lr(2, 8766 * 20.0, confidence=Confidence.HIGH),
                _lr(3, None, assumptions=("not available: ratings l0_hours and t0_rated needed",)),
            ],
            "mission_profile": MissionProfile(target_life_years=10),
        },
        tiers={10: 2},
    )
    html = render_lifetime(b)
    values = re.findall(r'<span class="value">([^<]*)</span><span class="badge t(\d)">', html)
    assert values == [("4.0 y", "2"), ("20.0 y", "1")]  # shortest life first, T2 badge kept
    assert html.count("<strong>below target</strong>") == 1
    assert "Not available" in html and "ratings l0_hours and t0_rated needed" in html
    assert "P3" in html and "2 estimate(s), 1 not available" in html
    assert "<p class='muted'>" in render_lifetime(FakeBundle())


def test_no_profile_gives_no_verdict() -> None:
    html = render_lifetime(FakeBundle(extras={"lifetime": [_lr(1, 100.0)]}))
    assert "<strong>below target</strong>" not in html and '<td class="">—</td>' in html


def test_services_registered() -> None:
    assert MODULE.services["report.sections"] is sections
    assert sections()[0][0] is SPEC and SPEC.requires == ("m7_lifetime",)
    assert MODULE.services["report.bundle_extras"] is bundle_extras


@pytest.mark.usefixtures("parts")
def test_bundle_extras_reads_profile_from_run(session, clock, design_version_id) -> None:
    from dfr.app.orchestrator import Orchestrator

    cfg = RunConfig().with_inputs(
        ConverterSpec(vin_min=7, vin_max=22, vout=3.3, iout_max=3.25, fsw=400e3, t_ambient=20),
        MissionProfile(target_life_years=7),
    )
    out = Orchestrator(session, [MODULE], clock=clock).run_analysis(design_version_id, cfg)
    extras = bundle_extras(session, out.run.id)
    assert extras["mission_profile"].target_life_years == 7
    assert [r.model_id for r in extras["lifetime"]] == ["thermal_cycling_coffin_manson"]
    assert bundle_extras(session, 999) == {"lifetime": [], "mission_profile": None}
