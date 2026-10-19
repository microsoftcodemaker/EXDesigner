from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dfr.core.contracts import (
    DeratingStatus,
    Part,
    PartClass,
    Rating,
    RatingProvenance,
    RatingSet,
    Source,
    Stat,
    StressValue,
    ThermalResult,
    Tier,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.modules.m5_derating.checker import evaluate_derating
from dfr.modules.m5_derating.ruleset import RULESETS_DIR, load_ruleset, load_ruleset_file, validate

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def part(
    pid: int, refdes: str, cls: PartClass, subtype: str | None = None, **ratings: float
) -> Part:
    return Part(
        id=pid,
        refdes=refdes,
        part_class=cls,
        subtype=subtype,
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit="", provenance=RatingProvenance.SEED)
                for k, v in ratings.items()
            }
        ),
    )


def sv(
    pid: int, param: str, value: float, scenario: str = "vin_max", sid: int | None = None
) -> StressValue:
    return StressValue(
        id=sid,
        part_id=pid,
        param=param,
        value=value,
        unit="A",
        stat=Stat.PEAK,
        scenario=scenario,
        source=Source.EQUATION,
        tier=Tier.T1,
        tool="t",
        tool_version="1",
        timestamp=NOW,
    )


def eff(*values: StressValue) -> dict:
    return {v.key: v for v in values}


@pytest.fixture(scope="module")
def rs():
    r = load_ruleset("generic_conservative")
    assert r is not None and r.rules
    return r


# ----------------------------------------------------------------------------- ruleset (DER-02/05)


def test_shipped_ruleset_valid_and_hashed(rs) -> None:
    assert rs.id == "generic_conservative" and rs.version == 1
    assert len(rs.sha256) == 64 and rs.diagnostics == []
    assert all(r.verify for r in rs.rules), "every shipped factor must be marked verify"
    assert all("verify" in r.source.lower() for r in rs.rules)


def test_subtype_rule_shadows_generic(rs) -> None:
    assert [r.id for r in rs.for_part("capacitor", "ceramic")] == ["cap_ceramic_voltage"]
    assert [r.id for r in rs.for_part("capacitor", "weird")] == ["cap_generic_voltage"]
    assert "res_power" in [r.id for r in rs.for_part("resistor", "chip")]


def test_missing_ruleset_is_none() -> None:
    assert load_ruleset("does_not_exist") is None


def test_schema_errors_have_line_numbers(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad\nversion: 1\nrules:\n"
        "  - { id: ok_rule, part_class: capacitor, param: v_dc, rating: v_rated, factor: 0.5, source: s }\n"
        "  - { id: bad_rule, part_class: capacitor, param: v_dc, rating: v_rated, factor: 7, source: s }\n"
        "  - { id: ok_rule, part_class: diode, param: v_peak, rating: v_rated, factor: 0.8, source: s }\n",
        encoding="utf-8",
    )
    r = load_ruleset_file(bad)
    assert r.rules == []
    msgs = [(d.message, d.line_no) for d in r.diagnostics]
    assert any("rules/1/factor" in m and ln == 5 for m, ln in msgs)
    assert any("duplicate rule id 'ok_rule'" in m for m, _ in msgs)
    assert validate({"id": "x"}) and validate({"id": "x"})[0].code == "RULESET_INVALID"
    broken = tmp_path / "broken.yaml"
    broken.write_text("rules: [\n", encoding="utf-8")
    assert load_ruleset_file(broken).diagnostics[0].message.startswith("YAML error")
    assert RULESETS_DIR.is_dir()


# ----------------------------------------------------------------------------- checker (DER-01/03/04)


def test_pass_warn_fail_boundaries(rs) -> None:
    c = part(1, "C1", PartClass.CAPACITOR, "ceramic", v_rated=50)
    # limit = 25 V
    for stress, status in (
        (25.0, DeratingStatus.PASS),
        (25.01, DeratingStatus.WARN),
        (50.0, DeratingStatus.WARN),
        (50.01, DeratingStatus.FAIL),
    ):
        r = evaluate_derating([c], eff(sv(1, "v_dc", stress, sid=11)), rs)[0]
        assert r.status is status, stress
        assert r.limit == 25 and r.rating == 50 and r.rule_id == "cap_ceramic_voltage"
        assert r.stress_value_ids == (11,)
    r = evaluate_derating([c], eff(sv(1, "v_dc", 20.0)), rs)[0]
    assert r.margin == pytest.approx(0.2) and r.ratio == pytest.approx(0.8)


def test_worst_scenario_is_checked(rs) -> None:
    c = part(1, "C1", PartClass.CAPACITOR, "ceramic", v_rated=50)
    rows = evaluate_derating(
        [c], eff(sv(1, "v_dc", 8, "vin_min"), sv(1, "v_dc", 36, "vin_max")), rs
    )
    assert len(rows) == 1 and rows[0].stress == 36 and rows[0].status is DeratingStatus.WARN


def test_missing_rating_is_unknown_never_pass(rs) -> None:
    sink = DiagnosticSink("t")
    L = part(2, "L1", PartClass.INDUCTOR, i_rated=4.2)  # no i_sat
    rows = evaluate_derating([L], eff(sv(2, "i_peak", 3.6), sv(2, "i_rms", 3.0)), rs, sink=sink)
    by = {r.rule_id: r for r in rows}
    assert by["ind_isat"].status is DeratingStatus.UNKNOWN and by["ind_isat"].limit is None
    assert by["ind_irms"].status is DeratingStatus.PASS
    assert any(d.code == "DERATING_NO_RATING" for d in sink)


def test_resistor_power_temperature_curve(rs) -> None:
    r = part(3, "R1", PartClass.RESISTOR, "chip", p_rated=0.1, t_knee=70, t_max=155)
    # at 40 C (below knee): limit = 0.1 * 1 * 0.5 = 0.05 W
    cold = evaluate_derating([r], eff(sv(3, "p_loss", 0.04)), rs, t_ambient=40)
    assert cold[0].limit == pytest.approx(0.05) and cold[0].status is DeratingStatus.PASS
    # at 112.5 C: scale = (155-112.5)/85 = 0.5 -> limit 0.025 W
    hot = evaluate_derating([r], eff(sv(3, "p_loss", 0.04)), rs, t_ambient=112.5)
    assert hot[0].limit == pytest.approx(0.025) and hot[0].status is DeratingStatus.WARN
    # no temperature -> flat factor with an info diagnostic
    sink = DiagnosticSink("t")
    flat = evaluate_derating([r], eff(sv(3, "p_loss", 0.04)), rs, sink=sink)
    assert flat[0].limit == pytest.approx(0.05) and any(
        d.code == "DERATING_CURVE_INCOMPLETE" for d in sink
    )


def test_tj_rule_uses_thermal_results_with_offset(rs) -> None:
    q = part(4, "Q1", PartClass.TRANSISTOR, "mosfet_n", tj_max=150, v_ds=60)
    thermal = [
        ThermalResult(part_id=4, scenario="vin_max", tj=120.0),
        ThermalResult(part_id=4, scenario="vin_min", tj=131.0),
    ]
    rows = evaluate_derating([q], eff(sv(4, "v_peak", 40)), rs, thermal=thermal)
    by = {r.rule_id: r for r in rows}
    assert (
        by["fet_tj"].stress == 131
        and by["fet_tj"].limit == 125
        and by["fet_tj"].status is DeratingStatus.WARN
    )
    assert by["fet_vds"].status is DeratingStatus.PASS
    # without thermal results the Tj rule is simply not evaluated
    assert "fet_tj" not in {r.rule_id for r in evaluate_derating([q], eff(sv(4, "v_peak", 40)), rs)}


def test_dnp_and_unsaved_parts_skipped(rs) -> None:
    dnp = part(5, "C9", PartClass.CAPACITOR, "ceramic", v_rated=10).model_copy(update={"dnp": True})
    unsaved = part(6, "C8", PartClass.CAPACITOR, "ceramic", v_rated=10).model_copy(
        update={"id": None}
    )
    assert evaluate_derating([dnp, unsaved], eff(sv(5, "v_dc", 9), sv(6, "v_dc", 9)), rs) == []
