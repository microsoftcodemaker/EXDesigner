from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dfr.core.contracts import (
    Net,
    NetKind,
    Part,
    Pin,
    PinFunctionProvenance,
    PromptOrigin,
    ProposalProvenance,
    Rail,
    Rating,
    RatingProvenance,
    RoleAssignment,
    RunConfig,
    RunStatus,
    Source,
    Stage,
    StageStatus,
    Stat,
    StressValue,
    Tier,
    ValuePrompt,
)
from dfr.core.db import migrate
from dfr.core.db.base import create_sqlite_engine
from dfr.core.db.repos import (
    DesignRepo,
    DiagnosticRepo,
    ImmutableRunError,
    NetlistRepo,
    PartRepo,
    RunRepo,
    StageRepo,
    StressRepo,
)
from dfr.core.db.repos.stress import resolve_effective_stress
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.ports import FixedClock
from tests.conftest import T0, make_part

CORE_TABLES = {
    "design",
    "design_version",
    "part",
    "rating",
    "net",
    "pin",
    "stage",
    "rail",
    "role_assignment",
    "stress_value",
    "value_prompt",
    "analysis_run",
    "effective_stress",
    "diagnostic",
}


# ----------------------------------------------------------------------------- migrations


def test_migrations_create_core_tables_and_module_branches(specs) -> None:
    eng = create_sqlite_engine()
    assert not migrate.is_up_to_date(eng, specs)
    migrate.upgrade_all(eng, specs)
    tables = set(inspect(eng).get_table_names())
    assert tables >= CORE_TABLES
    assert migrate.is_up_to_date(eng, specs)
    for s in migrate.module_branches(specs):
        assert any(t.startswith(s.table_prefix or s.id) for t in tables), s.id
    migrate.downgrade_all(eng, specs)
    assert set(inspect(eng).get_table_names()) == {"alembic_version"}


def test_deleting_a_module_keeps_db_usable_and_reinstall_resumes(specs) -> None:
    """MOD-03/MOD-05: version rows of absent modules are preserved, never fatal."""
    eng = create_sqlite_engine()
    migrate.upgrade_all(eng, specs)
    heads_before = migrate.current_heads(eng)
    orphans = migrate.upgrade_all(eng, [])  # as if every module folder were deleted
    assert set(orphans) == heads_before - {"0001_core"}
    assert migrate.is_up_to_date(eng, [])
    assert migrate.upgrade_all(eng, specs) == []  # re-installed: nothing orphaned, no re-create
    assert migrate.current_heads(eng) == heads_before


def test_foreign_keys_enforced(engine) -> None:
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO part (design_version_id, refdes, class, dnp, class_confidence) "
                "VALUES (999, 'C1', 'capacitor', 0, 1.0)"
            )
        )


# ----------------------------------------------------------------------------- design


def test_design_versions_append_only(session: Session, clock: FixedClock) -> None:
    repo = DesignRepo(session, clock)
    d = repo.create("A")
    v1 = repo.new_version(d.id, bom_hash="h1")
    v2 = repo.new_version(d.id, bom_hash="h2", netlist_hash="n1")
    assert (v1.version_no, v2.version_no) == (1, 2)
    assert repo.latest_version(d.id).id == v2.id
    assert [v.bom_hash for v in repo.versions(d.id)] == ["h1", "h2"]
    repo.rename(d.id, "B")
    assert repo.get(d.id).name == "B"
    assert [x.id for x in repo.list_all()] == [d.id]
    repo.delete(d.id)
    assert repo.get(d.id) is None
    assert repo.versions(d.id) == []  # cascade


# ----------------------------------------------------------------------------- parts


def test_part_crud_and_rating_provenance(session: Session, design_version_id: int) -> None:
    repo = PartRepo(session)
    p = repo.add(design_version_id, make_part("C1", ratings={"v_rated": (50, "V")}))
    assert p.id is not None
    got = repo.get(p.id)
    assert got is not None and got.ratings.get("v_rated").provenance is RatingProvenance.SEED
    repo.set_rating(
        p.id, Rating(name="v_rated", value=63, unit="V", provenance=RatingProvenance.USER)
    )
    repo.set_rating(
        p.id, Rating(name="i_ripple", value=1.2, unit="A", provenance=RatingProvenance.USER)
    )
    got = repo.by_refdes(design_version_id, "C1")
    assert got.ratings.get("v_rated").value == 63
    assert got.ratings.get("v_rated").provenance is RatingProvenance.USER
    assert set(got.ratings.ratings) == {"v_rated", "i_ripple"}


def test_duplicate_refdes_rejected(session: Session, design_version_id: int) -> None:
    repo = PartRepo(session)
    repo.add(design_version_id, make_part("C1"))
    with pytest.raises(IntegrityError):
        repo.add(design_version_id, make_part("C1"))


def test_dnp_filter(session: Session, design_version_id: int, parts: list[Part]) -> None:
    repo = PartRepo(session)
    assert len(repo.for_version(design_version_id)) == 5
    assert [p.refdes for p in repo.for_version(design_version_id, include_dnp=False)] == [
        "C5",
        "C6",
        "L1",
        "U3",
    ]
    repo.set_dnp(parts[0].id, True)
    assert len(repo.for_version(design_version_id, include_dnp=False)) == 3


# ----------------------------------------------------------------------------- netlist


def test_nets_and_pins(session: Session, design_version_id: int, parts: list[Part]) -> None:
    repo = NetlistRepo(session)
    sw = repo.add_net(design_version_id, Net(name="NetC3_1", normalized_name="NetC3_1"))
    gnd = repo.add_net(
        design_version_id, Net(name="GND", normalized_name="GND", kind=NetKind.GROUND)
    )
    u3 = next(p for p in parts if p.refdes == "U3")
    l1 = next(p for p in parts if p.refdes == "L1")
    repo.add_pin(u3.id, Pin(refdes="U3", pin_id="7"), sw.id)
    repo.add_pin(l1.id, Pin(refdes="L1", pin_id="1"), sw.id)
    pin3 = repo.add_pin(u3.id, Pin(refdes="U3", pin_id="3"), gnd.id)

    on_sw = repo.pins_on_net(sw.id)
    assert {(p.refdes, p.pin_id) for p in on_sw} == {("U3", "7"), ("L1", "1")}
    assert all(p.net_name == "NetC3_1" for p in on_sw)
    assert [p.pin_id for p in repo.pins_for_part(u3.id)] == ["3", "7"]

    repo.set_pin_function(pin3.id, "gnd", PinFunctionProvenance.USER)
    assert repo.pins_for_part(u3.id)[0].function_provenance is PinFunctionProvenance.USER

    repo.set_net_kind(sw.id, NetKind.POWER)
    assert repo.net_by_name(design_version_id, "NetC3_1").kind is NetKind.POWER
    assert repo.net_by_name(design_version_id, "NetC3_1").kind_provenance.value == "user"
    assert [n.name for n in repo.nets_for_version(design_version_id)] == ["GND", "NetC3_1"]


# ----------------------------------------------------------------------------- stage


def test_stage_roles_rails_confirm(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    nets = NetlistRepo(session)
    nets.add_net(design_version_id, Net(name="NetC3_1", normalized_name="NetC3_1"))
    repo = StageRepo(session, clock)
    stage = repo.add(
        design_version_id,
        Stage(
            pattern_id="buck_integrated",
            pattern_version="1.0.0",
            match_confidence=0.9,
            netlist_hash="abc",
            rails=[Rail(rail="sw", net_name="NetC3_1"), Rail(rail="vout", net_name="Buck_out")],
            assignments=[
                RoleAssignment(refdes="U3", role="ic", rail="sw", evidence="pin 7 on sw"),
                RoleAssignment(refdes="L1", role="inductor", rail="sw"),
                RoleAssignment(refdes="C5", role="output_cap", rail="vout"),
                RoleAssignment(refdes="C6", role="output_cap", rail="vout"),
                RoleAssignment(refdes="NOPE", role="other"),  # unmatched: silently skipped
            ],
        ),
    )
    assert stage.status is StageStatus.PROPOSED
    assert len(stage.assignments) == 4
    assert {a.provenance for a in stage.assignments} == {ProposalProvenance.PROPOSED}

    rm = repo.role_map(stage.id)
    assert rm.parts_with_role("output_cap") == ("C5", "C6")
    assert rm.rails == {"sw": "NetC3_1", "vout": "Buck_out"}

    repo.confirm(stage.id)
    confirmed = repo.get(stage.id)
    assert confirmed.status is StageStatus.CONFIRMED
    assert {a.provenance for a in confirmed.assignments} == {ProposalProvenance.USER}
    assert {r.provenance for r in confirmed.rails} == {ProposalProvenance.USER}

    repo.mark_stale(stage.id)
    assert repo.for_version(design_version_id)[0].status is StageStatus.STALE


# ----------------------------------------------------------------------------- stress


def sv(
    part_id: int,
    value: float,
    *,
    tier: Tier = Tier.T1,
    pinned: bool = False,
    dt: int = 0,
    source: Source = Source.EQUATION,
) -> StressValue:
    return StressValue(
        part_id=part_id,
        param="i_rms",
        value=value,
        unit="A",
        stat=Stat.RMS,
        scenario="vin_max",
        source=source,
        tier=tier,
        tool="t",
        tool_version="1",
        pinned=pinned,
        timestamp=T0 + timedelta(minutes=dt),
    )


def test_precedence_pinned_over_t2_over_t1() -> None:
    t1_old, t1_new = sv(1, 1.0, dt=0), sv(1, 1.1, dt=5)
    t2_old, t2_new = sv(1, 2.0, tier=Tier.T2, dt=1), sv(1, 2.1, tier=Tier.T2, dt=2)
    pinned = sv(1, 9.0, pinned=True, source=Source.MANUAL, dt=0)

    assert resolve_effective_stress([t1_old, t1_new])[t1_old.key].value == 1.1
    assert resolve_effective_stress([t1_new, t2_old, t2_new])[t1_old.key].value == 2.1
    assert resolve_effective_stress([t2_new, pinned, t1_new])[t1_old.key].value == 9.0
    other = sv(2, 5.0)
    eff = resolve_effective_stress([t1_old, other])
    assert len(eff) == 2


def test_stress_repo_append_only_and_prompts(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    repo = StressRepo(session, clock)
    c5 = parts[0]
    repo.add_many([sv(c5.id, 1.0), sv(c5.id, 1.2, dt=1)])
    assert [v.value for v in repo.for_part(c5.id)] == [1.0, 1.2]
    assert not hasattr(repo, "update") and not hasattr(repo, "delete")

    prompt = repo.add_prompt(
        design_version_id,
        ValuePrompt(
            part_id=c5.id,
            param="i_rms",
            stat="rms",
            scenario="vin_max",
            reason="ESR split unknown",
            how_to_obtain="measure ripple current in C5",
            origin=PromptOrigin.M2,
        ),
    )
    assert [p.id for p in repo.open_prompts(design_version_id)] == [prompt.id]
    answered = repo.answer_prompt(
        prompt.id, sv(c5.id, 1.5, tier=Tier.T2, source=Source.MEASURED, dt=2)
    )
    assert answered.id is not None
    assert repo.open_prompts(design_version_id) == []
    eff = repo.effective_for_version(design_version_id)
    assert eff[answered.key].value == 1.5 and eff[answered.key].tier is Tier.T2

    p2 = repo.add_prompt(
        design_version_id,
        ValuePrompt(
            part_id=None,
            param="v_peak",
            stat="peak",
            scenario="startup",
            reason="r",
            how_to_obtain="h",
            origin=PromptOrigin.M3,
        ),
    )
    repo.skip_prompt(p2.id)
    assert repo.open_prompts(design_version_id) == []
    with pytest.raises(LookupError):
        repo.answer_prompt(9999, sv(c5.id, 1.0))


def test_stress_value_provenance_columns_not_null(engine) -> None:
    cols = {c["name"]: c for c in inspect(engine).get_columns("stress_value")}
    for name in ("source", "tier", "tool", "tool_version", "timestamp"):
        assert cols[name]["nullable"] is False, name


# ----------------------------------------------------------------------------- runs


def test_run_lifecycle_and_immutability(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    runs = RunRepo(session, clock)
    diags = DiagnosticRepo(session)
    stress = StressRepo(session, clock)
    stored = stress.add(sv(parts[0].id, 1.0))

    cfg = RunConfig(ruleset_id="generic_conservative")
    run = runs.start(design_version_id, cfg, model_set={"example": "0.1.0"})
    assert run.status is RunStatus.RUNNING and run.finished_at is None
    runs.snapshot_effective(run.id, {stored.key: stored})
    sink = DiagnosticSink("m5")
    sink.warning("W", "warn", part_id=parts[0].id)
    assert diags.add_many(run.id, sink) == 1

    done = runs.finish(run.id)
    assert done.status is RunStatus.COMPLETED and done.finished_at == T0
    assert done.model_set == {"example": "0.1.0"}
    assert done.config.ruleset_id == "generic_conservative"
    assert [d.code for d in diags.for_run(run.id)] == ["W"]
    assert runs.effective_ids(run.id) == {stored.key: stored.id}

    with pytest.raises(ImmutableRunError):
        runs.finish(run.id, RunStatus.FAILED)
    with pytest.raises(ImmutableRunError):
        diags.add_many(run.id, sink)
    with pytest.raises(ImmutableRunError):
        runs.snapshot_effective(run.id, {})

    clock.advance(minutes=1)
    child = runs.start(design_version_id, cfg, parent_run_id=run.id, tier_level=Tier.T2)
    runs.finish(child.id)
    assert [r.id for r in runs.chain(child.id)] == [run.id, child.id]
    assert len(runs.for_version(design_version_id)) == 2
    with pytest.raises(LookupError):
        runs.finish(12345)


def test_snapshot_requires_persisted_values(
    session: Session, design_version_id: int, parts: list[Part], clock: FixedClock
) -> None:
    runs = RunRepo(session, clock)
    run = runs.start(design_version_id, RunConfig())
    unsaved = sv(parts[0].id, 1.0)
    with pytest.raises(ValueError, match="persisted"):
        runs.snapshot_effective(run.id, {unsaved.key: unsaved})
