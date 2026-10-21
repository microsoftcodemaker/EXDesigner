"""M9 FMEA: library validation, Occurrence scales, generator rules (PRD 3.9, FME-01/02)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dfr.core.contracts import (
    Confidence,
    FailureRateResult,
    LifetimeResult,
    MissionProfile,
    Part,
    PartClass,
    PartFailureRate,
    RoleMap,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.modules.m9_fmea.engine import (
    Override,
    generate,
    occurrence_from_fit,
    occurrence_from_life,
)
from dfr.modules.m9_fmea.library import load_library, load_library_file
from dfr.modules.m9_fmea.module import to_csv

FIT = (1, 3, 10, 30, 100, 200, 400, 700, 1000)
LIFE = (10, 5, 3, 2, 1.5, 1.2, 1.0, 0.7, 0.5)


def test_shipped_library_valid_and_fractions_sum_to_one() -> None:
    lib = load_library()
    assert lib.ok and not lib.diagnostics and "verify" in lib.source
    for subs in lib.classes.values():
        for modes in subs.values():
            assert sum(m.fraction for m in modes) == pytest.approx(1.0)
    assert lib.fit_upper == FIT and lib.life_ratio_lower == LIFE


def test_library_rejects_bad_fraction_and_schema(tmp_path: Path) -> None:
    src = (Path(__file__).parents[2] / "data" / "fmea" / "fmea_library.yaml").read_text("utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        src.replace("fraction: 0.6, wear_out: true }", "fraction: 0.7, wear_out: true }", 1),
        "utf-8",
    )
    lib = load_library_file(bad)
    assert not lib.ok and any("sum to 1.1" in d.message for d in lib.diagnostics)
    worse = tmp_path / "worse.yaml"
    worse.write_text(src.replace("severity: 6,", "severity: 11,", 1), "utf-8")
    assert not load_library_file(worse).ok


@pytest.mark.parametrize(
    ("fit", "o"), [(0.5, 1), (1.0, 1), (2.0, 2), (50, 5), (1000, 9), (1500, 10)]
)
def test_occurrence_from_fit(fit: float, o: int) -> None:
    assert occurrence_from_fit(fit, FIT) == o


@pytest.mark.parametrize(("ratio", "o"), [(20, 1), (5, 2), (1.0, 7), (0.6, 9), (0.1, 10)])
def test_occurrence_from_life(ratio: float, o: int) -> None:
    assert occurrence_from_life(ratio, LIFE) == o


def _part(ref: str, cls: PartClass, pid: int, subtype: str | None = None, **kw) -> Part:
    return Part(id=pid, refdes=ref, part_class=cls, subtype=subtype, **kw)


PARTS = [
    _part("C1", PartClass.CAPACITOR, 1, "ceramic"),
    _part("Q1", PartClass.TRANSISTOR, 2),
    _part("X1", PartClass.CRYSTAL, 3),
    _part("R9", PartClass.RESISTOR, 4, dnp=True),
]


def test_generate_occurrence_bases_and_overrides() -> None:
    rates = [
        FailureRateResult(
            method="pof", per_part=[PartFailureRate(part_id=2, lambda_fit=9999.0)]
        ),  # wear-out roll-up: never used as a constant rate
        FailureRateResult(
            method="mil_hdbk_217f",
            system_lambda_fit=60.0,
            per_part=[PartFailureRate(part_id=2, lambda_fit=50.0)],
        ),
    ]
    life = [
        LifetimeResult(
            part_id=1,
            mechanism="dielectric_wear_out",
            model_id="m",
            life_hours=87660.0 * 2,
            confidence=Confidence.LOW,
        )
    ]
    sink = DiagnosticSink("t")
    rows = generate(
        PARTS,
        load_library(),
        failure_rates=rates,
        lifetime=life,
        profile=MissionProfile(target_life_years=10),
        roles=RoleMap(roles={"high_side_switch": ("Q1",), "output_cap": ("C1",)}),
        overrides=[Override(2, "ds_short", severity=6, note="fused input")],
        sink=sink,
    )
    by = {(r.part_id, r.mode_id): r for r in rows}
    assert not any(r.part_id == 4 for r in rows)  # DNP skipped
    # C1 cap_loss is wear-out: life / target = 2 -> O 4; crack_short has no rate -> O 10
    assert by[(1, "cap_loss")].occurrence == 4 and by[(1, "cap_loss")].occurrence_basis == "life"
    assert by[(1, "crack_short")].occurrence == 10
    assert by[(1, "crack_short")].occurrence_basis == "no_data"
    assert "output_cap C1" in by[(1, "crack_short")].system_effect
    # Q1 ds_short: 50 FIT * 0.45 = 22.5 -> O 4 (<= 30); S overridden 10 -> 6
    ds = by[(2, "ds_short")]
    assert ds.lambda_fit == pytest.approx(22.5) and ds.occurrence == 4
    assert ds.occurrence_basis == "fit:mil_hdbk_217f"
    assert ds.severity == 6 and ds.source_flags["S"] == "user" and ds.rpn == 6 * 4 * 3
    assert ds.mitigation_note == "fused input"
    # Q1 rds_drift is wear-out without a life: falls back to the rate (50 * 0.2 = 10 -> O 3)
    assert by[(2, "rds_drift")].occurrence == 3
    # crystal not in the library -> generic rows + warning
    assert {r.mode_id for r in rows if r.part_id == 3} == {"open", "short"}
    assert any(d.code == "FMEA_GENERIC_ROWS" for d in sink.items)
    assert [r.rpn for r in rows] == sorted((r.rpn for r in rows), reverse=True)
    csv = to_csv(rows, {1: "C1", 2: "Q1", 3: "X1"})
    assert csv.splitlines()[0].startswith("refdes,mode,") and "fused input" in csv
