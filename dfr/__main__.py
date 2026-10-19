"""Command-line entry point: ``python -m dfr [status|demo]``.

``status`` lists discovered modules and the pipeline the orchestrator would build.
``demo`` creates an in-memory design with a few parts and runs one Tier 1 analysis
through the orchestrator, printing the run record and diagnostics. The GUI arrives in T19.
"""

from __future__ import annotations

import argparse
import sys

from dfr import __version__
from dfr.app import Orchestrator, plan_pipeline, summarize
from dfr.core.contracts import (
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
from dfr.core.db.base import create_sqlite_engine
from dfr.core.db.repos import DesignRepo, PartRepo, StressRepo
from dfr.core.db.session import make_session_factory, unit_of_work
from dfr.core.ports import SystemClock
from dfr.core.registry import discover


def cmd_status() -> int:
    result = discover()
    print(f"DfR Toolkit {__version__} (Python {sys.version.split()[0]})")
    print(f"\nDiscovered modules ({len(result.modules)}):")
    for m in result.modules:
        print(
            f"  {m.id:<16} v{m.version:<8} requires={list(m.requires)} provides={list(m.provides)}"
        )
    pipeline = plan_pipeline(result.modules, RunConfig())
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
        design = designs.create("Demo buck", topology_template="buck_integrated")
        version = designs.new_version(design.id, note="demo")
        parts = PartRepo(s).add_many(
            version.id,
            [
                _part("C5", PartClass.CAPACITOR, 22e-6, "F", v_rated=(10, "V")),
                _part("C6", PartClass.CAPACITOR, 22e-6, "F", v_rated=(10, "V")),
                _part("L1", PartClass.INDUCTOR, 10e-6, "H", i_sat=(4.2, "A")),
                _part("U3", PartClass.IC, None, None, tj_max=(150, "degC")),
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
        outcome = Orchestrator(s, specs, clock=clock).run_analysis(version.id, RunConfig())

    run = outcome.run
    print(f"Design '{design.name}' v{version.version_no}: run #{run.id} {run.status.value}")
    print(f"  tier={int(run.tier_level)} ruleset={run.ruleset_id} modules={run.model_set}")
    print(
        f"  pipeline={outcome.pipeline.ids} capabilities={sorted(outcome.context.capabilities())}"
    )
    print(
        f"  parts={len(outcome.context.get('parts'))} "
        f"effective_stress={len(outcome.context.get('effective_stress'))}"
    )
    print(f"  diagnostics={summarize(outcome.diagnostics)}")
    for d in outcome.diagnostics:
        print(f"    {d}")
    return 0 if outcome.ok else 1


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
    parser = argparse.ArgumentParser(prog="dfr", description=__doc__)
    parser.add_argument("command", nargs="?", choices=["status", "demo"], default="status")
    args = parser.parse_args(argv)
    return cmd_demo() if args.command == "demo" else cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())
