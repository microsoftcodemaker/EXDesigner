"""M2 binding against the real buck template (lives with the topology so the subtractive
matrix passes without it)."""

from __future__ import annotations

from dfr.core.contracts import PartClass, PromptOrigin
from dfr.core.ports import FixedClock
from dfr.modules.m2_conditions.service import compute_template_stress
from dfr.topologies.buck.template import BuckTemplate
from tests.m2_conditions.test_m2 import PARTS, ROLES, SPEC, part


def test_real_buck_template_creates_ic_loss_prompt(clock: FixedClock) -> None:
    out = compute_template_stress(BuckTemplate(integrated=True), SPEC, PARTS, ROLES, clock)
    assert len(out.stress) > 20
    assert [p.param for p in out.prompts] == ["p_loss"]
    p = out.prompts[0]
    assert p.part_id == 6 and p.origin is PromptOrigin.M2 and "efficiency" in p.how_to_obtain
    # supplying efficiency through part_params removes the prompt
    out2 = compute_template_stress(
        BuckTemplate(integrated=True), SPEC, PARTS, ROLES, clock, part_params={"eta": 0.9}
    )
    assert out2.prompts == []
    assert any(s.part_id == 6 and s.param == "p_loss" for s in out2.stress)


def test_ic_ratings_feed_template_params(clock: FixedClock) -> None:
    parts = [p if p.refdes != "U3" else part("U3", PartClass.IC, None, 6, eta=0.92) for p in PARTS]
    out = compute_template_stress(BuckTemplate(integrated=True), SPEC, parts, ROLES, clock)
    assert out.params["eta"] == 0.92 and out.prompts == []
