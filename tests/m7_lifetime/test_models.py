"""Lifetime models: vendor data present vs missing (LIF-01..06), confidence, assumptions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dfr.core.contracts import (
    Confidence,
    MissionProfile,
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
from dfr.modules.m7_lifetime.constants import MODELS_DIR, load_constants, load_constants_file
from dfr.modules.m7_lifetime.models import LifetimeContext, default_models
from dfr.modules.m7_lifetime.module import estimate_lifetimes

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def part(pid, refdes, cls=PartClass.CAPACITOR, subtype=None, attributes=None, **ratings) -> Part:
    return Part(
        id=pid,
        refdes=refdes,
        part_class=cls,
        subtype=subtype,
        attributes=attributes or {},
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit="", provenance=RatingProvenance.CATALOG)
                for k, v in ratings.items()
            }
        ),
    )


def sv(sid, pid, param, value, scenario="vin_max") -> StressValue:
    return StressValue(
        id=sid,
        part_id=pid,
        param=param,
        value=value,
        unit="A",
        stat=Stat.RMS,
        scenario=scenario,
        source=Source.EQUATION,
        tier=Tier.T1,
        tool="t",
        tool_version="1",
        timestamp=NOW,
    )


def eff(*values):
    return {v.key: v for v in values}


@pytest.fixture(scope="module")
def consts():
    c = load_constants("default")
    assert c is not None and c.version == 1 and c.diagnostics == []
    return c


def test_constants_file_valid_and_low_confidence(consts) -> None:
    assert len(consts.sha256) == 64 and MODELS_DIR.is_dir()
    assert (
        consts.electrolytic.degrees_per_doubling == 10 and consts.polymer.degrees_per_doubling == 20
    )
    assert (
        consts.electrolytic.confidence is Confidence.LOW and "verify" in consts.electrolytic.source
    )
    assert consts.mlcc("x7r")[1] == "X7R" and consts.mlcc(None)[1] == "default"
    assert consts.cycling_by_class["transistor"].n == 5 and consts.kb_ev_per_k == pytest.approx(
        8.617e-5
    )
    assert load_constants("nope") is None
    assert len(default_models(consts)) == 5


def test_constants_schema_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: bad\nversion: 1\nelectrolytic: {}\n", encoding="utf-8")
    c = load_constants_file(bad)
    assert (
        c.version == 0 and c.diagnostics and c.diagnostics[0].code == "LIFETIME_CONSTANTS_INVALID"
    )
    broken = tmp_path / "broken.yaml"
    broken.write_text("mlcc: [\n", encoding="utf-8")
    assert load_constants_file(broken).diagnostics[0].message.startswith("YAML error")


# ----------------------------------------------------------------------------- electrolytic (LIF-01)


def test_electrolytic_with_datasheet_data(consts) -> None:
    # Datasheet-style worked example: 5000 h at 105 degC, 2 A ripple, dT0 5 K.
    # Ta 45, Irms 1 A -> Tcore 46.25 -> L = 5000 * 2^(58.75/10) = 5000 * 58.69 = 293,452 h -> capped 15 y.
    c = part(
        1,
        "C10",
        subtype="aluminum_electrolytic",
        l0_hours=5000,
        t0_rated=105,
        i_ripple=2.0,
        dt0_core=5.0,
    )
    [r] = estimate_lifetimes([c], eff(sv(11, 1, "i_rms", 1.0)), consts, t_ambient=45)
    assert (
        r.model_id == "cap_aluminum_electrolytic_temperature_rule"
        and r.mechanism == "electrolyte_dry_out"
    )
    assert r.life_hours == pytest.approx(15 * 8766) and any("capped" in a for a in r.assumptions)
    assert r.input_stress_ids == (11,) and r.confidence is Confidence.LOW  # file constants are low
    # Hot: Ta 85, Irms 2 A -> Tcore 90 -> 5000 * 2^1.5 = 14,142 h, not capped.
    [hot] = estimate_lifetimes([c], eff(sv(12, 1, "i_rms", 2.0)), consts, t_ambient=85)
    assert hot.life_hours == pytest.approx(14142.1, rel=1e-3)
    # Above T0: Tcore 110 -> 5000 * 2^(-0.5) = 3535.5 h, extrapolated flag.
    [ext] = estimate_lifetimes([c], eff(sv(13, 1, "i_rms", 2.0)), consts, t_ambient=105)
    assert ext.life_hours == pytest.approx(3535.53, rel=1e-3) and any(
        "extrapolated" in a for a in ext.assumptions
    )


def test_electrolytic_missing_data_not_available(consts) -> None:
    sink = DiagnosticSink("t")
    no_l0 = part(1, "C10", subtype="aluminum_electrolytic", t0_rated=105)
    no_ripple = part(2, "C11", subtype="aluminum_electrolytic", l0_hours=5000, t0_rated=105)
    no_stress = part(3, "C12", subtype="aluminum_electrolytic", l0_hours=5000, t0_rated=105)
    seed_dt0 = part(4, "C13", subtype="polymer", l0_hours=2000, t0_rated=105, i_ripple=3.0)
    rows = estimate_lifetimes(
        [no_l0, no_ripple, no_stress, seed_dt0],
        eff(sv(1, 1, "i_rms", 1.0), sv(2, 2, "i_rms", 1.0), sv(4, 4, "i_rms", 3.0)),
        consts,
        t_ambient=45,
        sink=sink,
    )
    by = {r.part_id: r for r in rows}
    assert by[1].life_hours is None and "l0_hours and t0_rated" in by[1].assumptions[0]
    assert by[2].life_hours is None and "i_ripple" in by[2].assumptions[0]
    assert by[3].life_hours == pytest.approx(15 * 8766)  # 5000 * 2^6 = 320 kh, capped
    assert "core rise 0 K" in " ".join(by[3].assumptions)
    # polymer: 20-degree rule, seed dT0 2 K at rated ripple -> Tcore 47 -> 2000 * 2^(58/20)
    assert by[4].life_hours == pytest.approx(2000 * 2**2.9, rel=1e-3)
    assert by[4].confidence is Confidence.LOW and any(
        "seed default" in a for a in by[4].assumptions
    )
    assert sum(d.code == "LIFETIME_NOT_AVAILABLE" for d in sink) == 2


# ----------------------------------------------------------------------------- MLCC (LIF-02)


def test_mlcc_qualification_point_and_dielectric(consts) -> None:
    c = part(
        1,
        "C1",
        subtype="ceramic",
        attributes={"dielectric": "X7R"},
        l1_hours=1000,
        v1_test=100,
        t1_test=125,
    )
    [r] = estimate_lifetimes([c], eff(sv(5, 1, "v_dc", 50.0)), consts, t_ambient=125)
    assert r.life_hours == pytest.approx(8000, rel=1e-3) and r.confidence is Confidence.LOW
    assert "n = 3, Ea = 1.2 eV for X7R" in r.assumptions[0] and r.input_stress_ids == (5,)
    unknown = part(2, "C2", subtype="ceramic", l1_hours=1000, v1_test=100, t1_test=125)
    [u] = estimate_lifetimes([unknown], eff(sv(6, 2, "v_dc", 50.0)), consts, t_ambient=125)
    assert "for default" in u.assumptions[0] and u.life_hours == pytest.approx(8000, rel=1e-3)
    [na] = estimate_lifetimes(
        [part(3, "C3", subtype="ceramic")], eff(sv(7, 3, "v_dc", 5.0)), consts
    )
    assert na.life_hours is None and "qualification point" in na.assumptions[0]
    [nv] = estimate_lifetimes([c], eff(), consts)
    assert nv.life_hours is None and "no DC voltage stress" in nv.assumptions[0]


# ----------------------------------------------------------------------------- cycling (LIF-03)


def test_thermal_cycling_miner(consts) -> None:
    q = part(1, "Q1", PartClass.TRANSISTOR, tj_max=150)
    thermal = [ThermalResult(part_id=1, scenario="vin_max", tj=75.0, stress_value_ids=(9,))]
    # one on/off cycle of dTj 50 K x 365/year -> 8766 / (365/960)
    [r] = estimate_lifetimes([q], eff(), consts, thermal=thermal, t_ambient=25)
    assert r.life_hours == pytest.approx(23055.78, rel=1e-3) and r.input_stress_ids == (9,)
    assert any("one on/off cycle dTj = 50.0 K x 365/year" in a for a in r.assumptions)
    # rainflow bins win when present; cold-off ambient from the profile
    binned = [
        ThermalResult(
            part_id=1,
            scenario="n",
            tj=75.0,
            delta_tj_cycles=((50.0, 50.0, 365.0), (100.0, 75.0, 10.0)),
        )
    ]
    [b] = estimate_lifetimes([q], eff(), consts, thermal=binned)
    assert b.life_hours == pytest.approx(12285.2, rel=1e-3)
    prof = MissionProfile(on_off_cycles_per_year=365, t_ambient_off=-25)
    [cold] = estimate_lifetimes([q], eff(), consts, thermal=thermal, profile=prof, t_ambient=25)
    assert cold.life_hours == pytest.approx(8766 / (365 / (3e11 * 100**-5)), rel=1e-3)
    # no Tj -> not available; tiny swing -> no damage counted
    [na] = estimate_lifetimes([q], eff(), consts)
    assert na.life_hours is None and "no junction temperature" in na.assumptions[0]
    [tiny] = estimate_lifetimes(
        [q], eff(), consts, thermal=[ThermalResult(part_id=1, scenario="n", tj=27.0)], t_ambient=25
    )
    assert tiny.life_hours is None and any("no swing" in a for a in tiny.assumptions)


# ----------------------------------------------------------------------------- connector (LIF-04)


def test_connector_mating(consts) -> None:
    j = part(1, "J1", PartClass.CONNECTOR, mating_cycles=500)
    [r] = estimate_lifetimes([j], eff(), consts, profile=MissionProfile(mating_cycles_per_year=50))
    assert r.life_hours == pytest.approx(87660) and r.confidence is Confidence.MEDIUM
    [never] = estimate_lifetimes([j], eff(), consts)
    assert never.life_hours is None and "0 mating cycles" in never.assumptions[0]
    [na] = estimate_lifetimes([part(2, "J2", PartClass.CONNECTOR)], eff(), consts)
    assert na.life_hours is None and "mating_cycles" in na.assumptions[0]


def test_skips_and_target_warning(consts) -> None:
    sink = DiagnosticSink("t")
    dnp = part(1, "C9", subtype="ceramic", l1_hours=1, v1_test=1, t1_test=25).model_copy(
        update={"dnp": True}
    )
    short = part(2, "C8", subtype="ceramic", l1_hours=100, v1_test=10, t1_test=25)
    rows = estimate_lifetimes(
        [dnp, short], eff(sv(1, 2, "v_dc", 10.0)), consts, t_ambient=25, sink=sink
    )
    assert len(rows) == 1 and rows[0].life_hours == pytest.approx(100)
    assert any(d.code == "LIFETIME_BELOW_TARGET" for d in sink)
    ctx = LifetimeContext(consts, MissionProfile(), 25.0)
    assert ctx.profile.target_life_hours == pytest.approx(87660)
