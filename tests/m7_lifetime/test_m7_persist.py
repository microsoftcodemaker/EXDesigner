"""M7 through the orchestrator: rows persisted and read back via the service."""

from __future__ import annotations

from dfr.app.orchestrator import Orchestrator
from dfr.core.contracts import Confidence, MissionProfile, RunConfig
from dfr.modules.m7_lifetime.module import MODULE, load_results


def test_persist_and_load(session, clock, design_version_id, parts) -> None:
    orch = Orchestrator(session, [MODULE], clock=clock)
    profile = MissionProfile(target_life_years=5)
    out = orch.run_analysis(
        design_version_id, RunConfig(), extra_context={"mission_profile": profile}
    )
    assert out.ok and out.pipeline.ids == ["m7_lifetime"]
    rows = out.context.get("lifetime")
    refdes = {p.id: p.refdes for p in parts}
    # C5/C6 are capacitors without subtype -> no model; U3 (ic) -> cycling model, no Tj -> n/a
    assert [refdes[r.part_id] for r in rows] == ["U3"]
    assert rows[0].life_hours is None and rows[0].confidence is Confidence.LOW
    stored = load_results(session, out.run.id)
    assert len(stored) == 1 and stored[0].model_id == "thermal_cycling_coffin_manson"
    assert stored[0].assumptions == rows[0].assumptions
    assert any("target 5 y" in d.message for d in out.diagnostics if d.code == "LIFETIME_SUMMARY")
