"""Tier 2 CSV import (PRD 3.2 mode c, reduced form): validation, all-or-nothing, prompts."""

from __future__ import annotations

from dfr.core.contracts import PromptOrigin, Source, Stat, Tier, ValuePrompt
from dfr.core.db.repos import StressRepo
from dfr.modules.m2_conditions.csv_import import import_t2_csv, parse_t2_csv

GOOD = (
    "refdes,param,stat,scenario,value,unit,source,tool,note\n"
    "U3,p_loss,avg,vin_max,0.9,W,measured,bench,Pin-Pout\n"
    "L1,i_peak,peak,load_step,4.1,A,simulated,LTspice 24,\n"
    "\n"
    "C5,i_rms,rms,,0.12,A,Measured,,\n"
)


def test_parse_good_file(clock, parts) -> None:
    ids = {p.refdes: p.id for p in parts}
    values, sha, diags = parse_t2_csv(GOOD, "bench.csv", ids, clock)
    assert len(sha) == 64 and diags == [] and len(values) == 3
    u3 = values[0]
    assert u3.part_id == ids["U3"] and u3.tier is Tier.T2 and u3.source is Source.MEASURED
    assert u3.stat is Stat.AVG and u3.scenario == "vin_max" and u3.note == "Pin-Pout"
    assert u3.tool == "csv:bench.csv (bench)" and u3.tool_version == sha[:12]
    assert values[1].tool == "csv:bench.csv (LTspice 24)" and values[1].source is Source.SIMULATED
    assert (
        values[2].scenario == "nominal"
        and values[2].note is None
        and values[2].timestamp == clock.now()
    )


def test_errors_are_line_numbered_and_reject_everything(clock, parts) -> None:
    ids = {p.refdes: p.id for p in parts}
    bad = (
        "Refdes,Param,Stat,Value,Unit,Source,extra\n"
        "U3,p_loss,avg,0.9,W,measured,x\n"  # ok
        "Q9,i_rms,rms,1,A,measured,\n"  # line 3: unknown refdes
        "L1,i_peak,max,1,A,measured,\n"  # line 4: bad stat
        "L1,i_peak,peak,abc,A,measured,\n"  # line 5: bad value
        "L1,i_peak,peak,1,blorps,measured,\n"  # line 6: bad unit
        "L1,i_peak,peak,1,A,equation,\n"  # line 7: not a T2 source
        "L1,,peak,1,A,guess,\n"  # line 8: empty param + unknown source
    )
    values, _, diags = parse_t2_csv(bad, "bad.csv", ids, clock)
    assert values == []
    by_line = {(d.code, d.line_no) for d in diags}
    assert ("T2_CSV_UNKNOWN_COLUMN", 1) in by_line
    assert {
        ("T2_CSV_REFDES", 3),
        ("T2_CSV_STAT", 4),
        ("T2_CSV_VALUE", 5),
        ("T2_CSV_UNIT", 6),
        ("T2_CSV_SOURCE", 7),
        ("T2_CSV_PARAM", 8),
        ("T2_CSV_SOURCE", 8),
    } <= by_line
    assert any("not in {peak, rms, avg, min, dc}" in d.message for d in diags)

    _, _, hdr = parse_t2_csv("refdes,value\nU3,1\n", "h.csv", ids, clock)
    assert hdr[0].code == "T2_CSV_HEADER" and "param, stat, unit, source" in hdr[0].message
    _, _, empty = parse_t2_csv("refdes,param,stat,value,unit,source\n", "e.csv", ids, clock)
    assert empty[0].code == "T2_CSV_EMPTY"


def test_import_stores_rows_and_answers_matching_prompt(
    session, clock, design_version_id, parts
) -> None:
    repo = StressRepo(session, clock)
    u3 = next(p for p in parts if p.refdes == "U3")
    prompt = repo.add_prompt(
        design_version_id,
        ValuePrompt(
            part_id=u3.id,
            param="p_loss",
            stat="avg",
            scenario="vin_max",
            reason="r",
            how_to_obtain="h",
            origin=PromptOrigin.M2,
        ),
    )
    out = import_t2_csv(session, clock, design_version_id, GOOD, "bench.csv")
    assert out.ok and len(out.stored) == 3 and all(v.id is not None for v in out.stored)
    assert out.answered_prompt_ids == [prompt.id] and repo.open_prompts(design_version_id) == []
    assert any(d.code == "T2_CSV_IMPORTED" and "3 Tier 2" in d.message for d in out.diagnostics)
    eff = repo.effective_for_version(design_version_id)
    assert eff[(u3.id, "p_loss", "vin_max")].tier is Tier.T2

    # A bad file writes nothing.
    before = len(repo.for_version(design_version_id))
    bad = import_t2_csv(
        session,
        clock,
        design_version_id,
        "refdes,param,stat,value,unit,source\nZZ,x,peak,1,A,measured\n",
        "bad.csv",
    )
    assert not bad.ok and bad.stored == [] and len(repo.for_version(design_version_id)) == before
