from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dfr.core.contracts import (
    DeratingResult,
    DeratingStatus,
    Part,
    PartClass,
    PromptOrigin,
    Rating,
    RatingProvenance,
    RatingSet,
    RoleMap,
    Source,
    Stat,
    StressValue,
    ThermalResult,
    Tier,
    ValuePrompt,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.modules.m3_triage.config import TRIAGE_DIR, load_config, load_config_file, validate
from dfr.modules.m3_triage.engine import Waiver, clamp01, triage

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def part(pid: int, refdes: str, cls: PartClass = PartClass.CAPACITOR, **ratings: float) -> Part:
    return Part(
        id=pid,
        refdes=refdes,
        part_class=cls,
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit="", provenance=RatingProvenance.SEED)
                for k, v in ratings.items()
            }
        ),
    )


def sv(
    sid: int, pid: int, param: str, scenario: str = "vin_max", tier: Tier = Tier.T1
) -> StressValue:
    return StressValue(
        id=sid,
        part_id=pid,
        param=param,
        value=1.0,
        unit="A",
        stat=Stat.PEAK,
        scenario=scenario,
        source=Source.EQUATION if tier is Tier.T1 else Source.MEASURED,
        tier=tier,
        tool="t",
        tool_version="1",
        timestamp=NOW,
    )


def dr(
    pid: int, param: str, margin: float | None, status: DeratingStatus, ids=(), rule="r"
) -> DeratingResult:
    ratio = None if margin is None else 1 - margin
    return DeratingResult(
        part_id=pid,
        param=param,
        stress=1.0,
        limit=None if margin is None else 1.0,
        rating=None if margin is None else 1.5,
        ratio=ratio,
        status=status,
        margin=margin,
        rule_id=rule,
        stress_value_ids=tuple(ids),
    )


@pytest.fixture(scope="module")
def cfg():
    c = load_config("default")
    assert c is not None and c.version == 1
    return c


# ----------------------------------------------------------------------------- config (TRI-01)


def test_shipped_config_valid_hashed_and_verify_marked(cfg) -> None:
    assert len(cfg.sha256) == 64 and cfg.diagnostics == []
    assert (cfg.w1_margin, cfg.w2_thermal, cfg.w3_lifetime, cfg.w4_blind_spot) == (
        0.35,
        0.25,
        0.25,
        0.15,
    )
    assert cfg.margin_threshold == 0.15 and cfg.tj_proximity_c == 20.0
    assert "verify" in cfg.source.lower() and all(
        "verify" in b.source.lower() for b in cfg.blind_spots
    )
    assert {b.id for b in cfg.spots_for("buck_integrated", {"ic"})} == {"sw_vds_ringing"}
    assert cfg.spots_for("boost", {"inductor", "catch_diode"}) and not cfg.spots_for(None, {"ic"})
    assert load_config("nope") is None and TRIAGE_DIR.is_dir()


def test_config_schema_errors_have_line_numbers(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad\nversion: 1\nthresholds: { margin: 0.15, tj_proximity_c: 20 }\n"
        "weights: { w1_margin: 0.35, w2_thermal: 0.25, w3_lifetime: 0.25, w4_blind_spot: 0.15 }\n"
        "blind_spots:\n"
        "  - { id: a, topologies: [buck], roles: [ic], param: v_peak, stat: peak, scenario: vin_max, weight: 1, reason: r, how: h, source: s }\n"
        "  - { id: a, topologies: [buck], roles: [ic], param: v_peak, stat: bogus, scenario: vin_max, weight: 1, reason: r, how: h, source: s }\n",
        encoding="utf-8",
    )
    c = load_config_file(bad)
    assert c.version == 0 and c.blind_spots == []
    msgs = [(d.message, d.line_no) for d in c.diagnostics]
    assert any("blind_spots/1/stat" in m and ln == 7 for m, ln in msgs)
    assert any("duplicate blind-spot id 'a'" in m for m, _ in msgs)
    assert validate({"id": "x"})[0].code == "TRIAGE_CONFIG_INVALID"
    broken = tmp_path / "broken.yaml"
    broken.write_text("weights: [\n", encoding="utf-8")
    assert load_config_file(broken).diagnostics[0].message.startswith("YAML error")


# ----------------------------------------------------------------------------- ranking (TRI-02/05)


def test_ranking_order_and_scores(cfg) -> None:
    """Hand-calculated PRD 3.3 scores: F1 = w1*clamp(1 - margin/0.15), F0 = w1*no_data."""
    parts = [
        part(1, "C1"),
        part(2, "C2"),
        part(3, "L1", PartClass.INDUCTOR),
        part(4, "R1", PartClass.RESISTOR),
    ]
    rows = [
        dr(1, "v_dc", 0.12, DeratingStatus.PASS, ids=(11,)),  # 0.35*(1-0.8)=0.07
        dr(2, "v_dc", -0.26, DeratingStatus.WARN, ids=(12,)),  # clamp -> 0.35
        dr(3, "i_peak", None, DeratingStatus.UNKNOWN, ids=(13,)),  # F0 -> 0.35
        dr(3, "i_rms", 0.03, DeratingStatus.PASS, ids=(14,)),  # 0.35*(1-0.2)=0.28
        dr(4, "p_loss", 0.5, DeratingStatus.PASS),  # not flagged
    ]
    eff = {
        v.key: v
        for v in (
            sv(11, 1, "v_dc"),
            sv(12, 2, "v_dc"),
            sv(13, 3, "i_peak", "vin_min"),
            sv(14, 3, "i_rms"),
        )
    }
    items = triage(parts, rows, cfg, effective=eff)
    assert [i.part_id for i in items] == [3, 2, 1]
    assert [i.score for i in items] == pytest.approx([0.63, 0.35, 0.07])
    l1 = items[0]
    assert l1.flags == ["F0", "F1"] and l1.parameters_to_refine == ["i_rms"]
    assert l1.recommended_scenarios == ["vin_max"]
    assert any("no rating" in r and "UNKNOWN" in r for r in l1.reasons)
    assert any("97 % of derated limit; margin 3 % < 15 %" in r for r in l1.reasons)
    assert all(i.status == "open" for i in items) and not any(i.prompts for i in items)


def test_missing_rating_always_flags_f0(cfg) -> None:
    items = triage(
        [part(1, "L1", PartClass.INDUCTOR)], [dr(1, "i_peak", None, DeratingStatus.UNKNOWN)], cfg
    )
    assert len(items) == 1 and items[0].flags == ["F0"] and items[0].score == pytest.approx(0.35)


def test_thermal_proximity_f2_and_missing_tjmax(cfg) -> None:
    q = part(1, "Q1", PartClass.TRANSISTOR, tj_max=150)
    u = part(2, "U1", PartClass.IC)
    thermal = [
        ThermalResult(part_id=1, scenario="vin_min", tj=120.0),
        ThermalResult(part_id=1, scenario="vin_max", tj=140.0),  # headroom 10 -> 0.25*(1-0.5)
        ThermalResult(part_id=2, scenario="vin_max", tj=90.0),
    ]
    items = {i.part_id: i for i in triage([q, u], [], cfg, thermal=thermal)}
    assert items[1].flags == ["F2"] and items[1].score == pytest.approx(0.125)
    assert (
        "within 10 degC of Tjmax 150 degC" in items[1].reasons[0]
        and "[vin_max]" in items[1].reasons[0]
    )
    assert items[1].parameters_to_refine == ["p_loss"] and items[1].recommended_scenarios == [
        "vin_max"
    ]
    assert items[2].flags == ["F0"] and "no tj_max rating" in items[2].reasons[0]
    assert triage([q], [], cfg, thermal=[ThermalResult(part_id=1, scenario="n", tj=100.0)]) == []


def test_lifetime_shortfall_f3_and_no_data(cfg) -> None:
    from dfr.core.contracts import Confidence, LifetimeResult, MissionProfile

    c10, c11, q1 = part(1, "C10"), part(2, "C11"), part(3, "Q1", PartClass.TRANSISTOR)
    life = [
        LifetimeResult(
            part_id=1,
            mechanism="electrolyte_dry_out",
            model_id="m",
            life_hours=5 * 8766,
            confidence=Confidence.LOW,
        ),
        LifetimeResult(
            part_id=2,
            mechanism="dielectric_wear_out",
            model_id="m",
            life_hours=None,
            confidence=Confidence.LOW,
            assumptions=("not available: no vendor data",),
        ),
        LifetimeResult(
            part_id=3,
            mechanism="thermal_cycling_fatigue",
            model_id="m",
            life_hours=50 * 8766,
            confidence=Confidence.LOW,
        ),
    ]
    items = {
        i.part_id: i
        for i in triage(
            [c10, c11, q1], [], cfg, lifetime=life, profile=MissionProfile(target_life_years=10)
        )
    }
    assert items[1].flags == ["F3"] and items[1].score == pytest.approx(
        0.25 * 0.5
    )  # w3 * (1 - 5/10)
    assert "life 5.0 y < target 10 y (low confidence" in items[1].reasons[0]
    assert items[2].flags == ["F0"] and items[2].score == pytest.approx(
        0.125
    )  # w3 * no_lifetime_data
    assert "not available: no vendor data" in items[2].reasons[0]
    assert 3 not in items  # 50 y >= target
    waived = triage([c10], [], cfg, lifetime=life[:1], waivers=[Waiver(1, "F3", "spares planned")])
    assert waived[0].status == "waived" and waived[0].waiver_reason == "spares planned"


# ----------------------------------------------------------------------------- F4 prompts (TRI-06)


def test_blind_spot_prompts_and_dedup(cfg) -> None:
    u = part(1, "U3", PartClass.IC)
    c1, c2 = part(2, "C1"), part(3, "C2")
    roles = RoleMap(roles={"ic": ("U3",), "input_cap": ("C1", "C2")})
    items = triage([u, c1, c2], [], cfg, topology="buck_integrated", roles=roles)
    by = {i.part_id: i for i in items}
    assert by[1].flags == ["F4:sw_vds_ringing"] and by[1].score == pytest.approx(0.15)
    p = by[1].prompts[0]
    assert isinstance(p, ValuePrompt) and p.origin is PromptOrigin.M3
    assert (p.param, p.stat, p.scenario) == (
        "v_peak",
        "peak",
        "vin_max",
    ) and "scope" in p.how_to_obtain
    assert by[2].score == pytest.approx(0.09) and by[2].prompts[0].scenario == "startup"
    # an already-open prompt for the same (part, param, scenario) is not requested twice
    again = triage([u], [], cfg, topology="buck_integrated", roles=roles, existing_prompts=[p])
    assert again[0].flags == ["F4:sw_vds_ringing"] and again[0].prompts == []
    # unknown topology -> no blind spots
    assert triage([u], [], cfg, topology="mystery", roles=roles) == []


# ----------------------------------------------------------------------------- TRI-03 / TRI-04


def test_refined_parameters_are_not_reflagged(cfg) -> None:
    sink = DiagnosticSink("t")
    u = part(1, "U3", PartClass.IC)
    roles = RoleMap(roles={"ic": ("U3",)})
    eff = {v.key: v for v in (sv(21, 1, "i_out", tier=Tier.T2), sv(22, 1, "v_peak", tier=Tier.T2))}
    rows = [dr(1, "i_out", -0.25, DeratingStatus.WARN, ids=(21,))]
    items = triage(
        [u], rows, cfg, effective=eff, topology="buck_integrated", roles=roles, sink=sink
    )
    assert items == []
    assert sum(d.code == "TRIAGE_ALREADY_REFINED" for d in sink) == 2


def test_waivers_keep_item_with_reason(cfg) -> None:
    c2 = part(1, "C2")
    rows = [dr(1, "v_dc", -0.26, DeratingStatus.WARN, ids=(12,))]
    waived = triage([c2], rows, cfg, waivers=[Waiver(1, "F1", "35 V part, 22 V transient only")])
    assert len(waived) == 1 and waived[0].status == "waived" and waived[0].flags == ["F1"]
    assert waived[0].waiver_reason == "35 V part, 22 V transient only" and waived[0].score == 0
    # a part with one open and one waived flag stays open, waived flags listed after open ones
    mixed = triage(
        [c2],
        [*rows, dr(1, "i_rms", None, DeratingStatus.UNKNOWN)],
        cfg,
        waivers=[Waiver(1, "F1", "ok")],
    )
    assert (
        mixed[0].status == "open"
        and mixed[0].flags == ["F0", "F1"]
        and mixed[0].waiver_reason == "ok"
    )
    # waived items sort after open ones regardless of score
    both = triage(
        [c2, part(2, "C1")],
        [*rows, dr(2, "v_dc", 0.12, DeratingStatus.PASS)],
        cfg,
        waivers=[Waiver(1, "F1", "ok")],
    )
    assert [i.part_id for i in both] == [2, 1]


def test_clamp_and_skips() -> None:
    assert clamp01(-1) == 0 and clamp01(2) == 1 and clamp01(0.3) == 0.3
    cfg = load_config("default")
    dnp = part(1, "C9").model_copy(update={"dnp": True})
    unsaved = part(2, "C8").model_copy(update={"id": None})
    assert (
        triage(
            [dnp, unsaved],
            [dr(1, "v_dc", -1, DeratingStatus.FAIL), dr(2, "v_dc", -1, DeratingStatus.FAIL)],
            cfg,
        )
        == []
    )
