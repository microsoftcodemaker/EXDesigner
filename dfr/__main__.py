"""Command-line entry point: ``python -m dfr [status|demo|analyze ...]``.

``status``  lists discovered modules and the pipeline the orchestrator would build.
``demo``    runs one Tier 1 analysis on a tiny in-memory design (no topology).
``analyze`` imports a BOM + netlist, matches the selected topology, auto-confirms the
            proposal (CLI only; the GUI requires an explicit confirm), runs Tier 1 and prints
            the derating table. Example:
            python -m dfr analyze --bom tests/fixtures/design_c/design_c.BomDoc
                --netlist tests/fixtures/design_c/design_c_protel.net --topology buck_integrated
                --vin-min 8 --vin-max 36 --vout 3.3 --iout 3.25 --fsw 400e3 --ta 40
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dfr import __version__
from dfr.app import AnalysisInputs, Orchestrator, plan_pipeline, run_tier1, summarize
from dfr.app.workflow import import_design, match_and_confirm
from dfr.core.contracts import (
    ConverterSpec,
    DeratingResult,
    DeratingStatus,
    Diagnostic,
    Part,
    PartClass,
    Rating,
    RatingProvenance,
    RatingSet,
    RunConfig,
    Source,
    Stat,
    StressValue,
    Tier,
)
from dfr.core.db import migrate
from dfr.core.db.base import create_sqlite_engine, sqlite_url
from dfr.core.db.repos import DesignRepo, PartRepo, StressRepo
from dfr.core.db.session import make_session_factory, unit_of_work
from dfr.core.ports import SystemClock
from dfr.core.registry import discover


def cmd_status() -> int:
    result = discover()
    print(f"DfR Toolkit {__version__} (Python {sys.version.split()[0]})")
    print(f"\nDiscovered modules ({len(result.modules)}):")
    for m in result.modules:
        kind = "step" if m.step else "services"
        print(
            f"  {m.id:<16} v{m.version:<8} {kind:<8} requires={list(m.requires)} provides={list(m.provides)}"
        )
    pipeline = plan_pipeline(
        result.modules, RunConfig(), ["role_map", "converter_spec", "templates", "stage"]
    )
    print(f"\nPipeline order: {pipeline.ids or '(empty)'}")
    for mid, reason in pipeline.skipped.items():
        print(f"  skipped {mid}: {reason}")
    for d in [*result.diagnostics, *pipeline.diagnostics]:
        print(f"  {d}")
    return 0


def cmd_demo() -> int:
    clock = SystemClock()
    specs = discover().modules
    engine = create_sqlite_engine()
    migrate.upgrade_all(engine, specs)
    factory = make_session_factory(engine)
    with unit_of_work(factory) as s:
        designs = DesignRepo(s, clock)
        design = designs.create("Demo", topology_template=None)
        version = designs.new_version(design.id, note="demo")
        parts = PartRepo(s).add_many(
            version.id,
            [
                _part("C5", PartClass.CAPACITOR, 22e-6, "F", v_rated=(10, "V")),
                _part("L1", PartClass.INDUCTOR, 10e-6, "H", i_sat=(4.2, "A")),
            ],
        )
        l1 = next(p for p in parts if p.refdes == "L1")
        StressRepo(s, clock).add(
            StressValue(
                part_id=l1.id or 0,
                param="i_peak",
                value=3.84,
                unit="A",
                stat=Stat.PEAK,
                scenario="vin_max",
                source=Source.MANUAL,
                tier=Tier.T1,
                tool="demo",
                tool_version=__version__,
                timestamp=clock.now(),
            )
        )
        outcome = Orchestrator(s, specs, clock=clock).run_analysis(
            version.id, RunConfig(enabled_modules=("example", "m5_derating", "m6_thermal"))
        )
    print(
        f"Design '{design.name}' v{version.version_no}: run #{outcome.run.id} {outcome.run.status.value}"
    )
    print(f"  pipeline={outcome.pipeline.ids} diagnostics={summarize(outcome.diagnostics)}")
    _print_derating(outcome.context.get_or("derating", []), {p.id: p for p in parts})
    return 0 if outcome.ok else 1


def cmd_analyze(a: argparse.Namespace) -> int:
    clock = SystemClock()
    registry = discover()
    engine = create_sqlite_engine(sqlite_url(a.db) if a.db else "sqlite+pysqlite:///:memory:")
    migrate.upgrade_all(engine, registry.modules)
    factory = make_session_factory(engine)
    spec = ConverterSpec(
        vin_min=a.vin_min,
        vin_max=a.vin_max,
        vout=a.vout,
        iout_max=a.iout,
        fsw=a.fsw,
        t_ambient=a.ta,
    )

    with unit_of_work(factory) as s:
        imported = import_design(
            s,
            registry,
            clock,
            name=a.name,
            bom_path=Path(a.bom),
            netlist_path=Path(a.netlist),
            topology=a.topology,
        )
        print(
            f"Imported {imported.part_count} parts, {imported.net_count} nets -> design #{imported.design_id} v{imported.design_version_id}"
        )
        _print_diags(imported.diagnostics, a.verbose)
        if imported.pinout_requests:
            print(
                f"  pinouts requested for: {', '.join(q.refdes for q in imported.pinout_requests)} "
                "(matching uses connectivity only; pin names are needed before confirmation in the GUI)"
            )

        stage, diags = match_and_confirm(
            s, registry, clock, imported, topology=a.topology, auto_confirm=True
        )
        _print_diags(diags, a.verbose)
        if stage is None:
            print("No stage matched; stopping.")
            return 1
        print(
            f"\nStage {stage.pattern_id} confidence {stage.match_confidence:.2f} (auto-confirmed for CLI)"
        )
        for r in stage.rails:
            print(f"  rail {r.rail:<5} = {r.net_name}")
        for asg in stage.assignments:
            if asg.role != "other":
                print(f"  {asg.refdes:<4} {asg.role:<14} {asg.evidence}")

        outcome = run_tier1(
            s, registry, AnalysisInputs(imported.design_version_id, spec), clock=clock
        )
        parts = {p.id: p for p in PartRepo(s).for_version(imported.design_version_id)}

    print(f"\nRun #{outcome.run.id} {outcome.run.status.value}: pipeline={outcome.pipeline.ids}")
    print(
        f"  spec: Vin {spec.vin_min}-{spec.vin_max} V, Vout {spec.vout} V, Iout {spec.iout_max} A, fsw {spec.fsw:g} Hz, Ta {spec.t_ambient} C"
    )
    inferred = outcome.context.get_or("inferred_values")
    if inferred:
        for k, v in inferred.values.items():
            print(
                f"  inferred {k:<7} = {v.value:.4g} {v.unit:<3} from {', '.join(v.contributing_refdes) or v.provenance}"
            )
    stress = outcome.context.get_or("stress", [])
    print(
        f"  stress values: {len(stress)} (T1 equation)   prompts: {len(outcome.context.get_or('prompts', []))}"
    )
    for p in outcome.context.get_or("prompts", []):
        owner = parts.get(p.part_id)
        who = owner.refdes if owner is not None else "?"
        print(f"    PROMPT {who} {p.param}: {p.reason}")
    for t in outcome.context.get_or("thermal", []):
        print(
            f"  thermal {parts[t.part_id].refdes} [{t.scenario}] Tj = {t.tj:.1f} C{'  RUNAWAY' if t.runaway_flag else ''}"
        )
    _print_derating(outcome.context.get_or("derating", []), parts)
    print(f"  diagnostics: {summarize(outcome.diagnostics)}")
    _print_diags(outcome.diagnostics, a.verbose)
    return 0 if outcome.ok else 1


def _print_derating(rows: list[DeratingResult], parts: dict[int | None, Part]) -> None:
    if not rows:
        print("  derating: no rows")
        return
    print(
        f"\n  {'part':<5}{'param':<9}{'stress':>10}{'limit':>10}{'rating':>10}{'margin':>9}  status   rule"
    )
    order = {
        DeratingStatus.FAIL: 0,
        DeratingStatus.WARN: 1,
        DeratingStatus.UNKNOWN: 2,
        DeratingStatus.PASS: 3,
    }
    for r in sorted(rows, key=lambda r: (order[r.status], r.margin if r.margin is not None else 0)):
        ref = parts[r.part_id].refdes if r.part_id in parts else str(r.part_id)
        margin = f"{r.margin * 100:>8.1f}%" if r.margin is not None else f"{'-':>9}"
        print(
            f"  {ref:<5}{r.param:<9}{_num(r.stress)}{_num(r.limit)}{_num(r.rating)}{margin}"
            f"  {r.status.value.upper():<8} {r.rule_id}"
        )


def _num(x: float | None) -> str:
    return f"{x:>10.4g}" if x is not None else f"{'-':>10}"


def _print_diags(diags: list[Diagnostic], verbose: bool) -> None:
    for d in diags:
        if verbose or d.severity.value != "info":
            print(f"    {d}")


def _part(
    refdes: str, cls: PartClass, value: float | None, unit: str | None, **ratings: tuple[float, str]
) -> Part:
    return Part(
        refdes=refdes,
        part_class=cls,
        value_si=value,
        value_unit=unit,
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit=u, provenance=RatingProvenance.SEED)
                for k, (v, u) in ratings.items()
            }
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dfr", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("demo")
    an = sub.add_parser("analyze")
    an.add_argument("--bom", required=True)
    an.add_argument("--netlist", required=True)
    an.add_argument("--topology", default="buck_integrated")
    an.add_argument("--name", default="CLI design")
    an.add_argument("--db", default=None, help="SQLite file to keep results (default: in-memory)")
    an.add_argument("--vin-min", type=float, required=True)
    an.add_argument("--vin-max", type=float, required=True)
    an.add_argument("--vout", type=float, required=True)
    an.add_argument("--iout", type=float, required=True)
    an.add_argument("--fsw", type=float, required=True)
    an.add_argument("--ta", type=float, default=25.0)
    an.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return cmd_demo()
    if args.command == "analyze":
        return cmd_analyze(args)
    return cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())
