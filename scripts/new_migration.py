"""Create a new Alembic revision on the core branch or a module branch.

Usage:
    python scripts/new_migration.py core "add column x"
    python scripts/new_migration.py <module_id> "create table y" [--autogenerate]

Module branches live in ``dfr/modules/<folder>/migrations`` and are labelled with the
module id (``ModuleSpec.id``). Autogenerate only sees core metadata; module tables are
written by hand (they are small and prefixed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import command

from dfr.core.db import migrate
from dfr.core.db.base import create_sqlite_engine
from dfr.core.registry import discover


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("branch", help="'core' or a module id")
    parser.add_argument("message")
    parser.add_argument("--autogenerate", action="store_true")
    args = parser.parse_args()

    specs = discover(entry_points=False).modules
    engine = create_sqlite_engine()
    cfg = migrate.make_config(engine, specs)

    if args.branch == migrate.CORE_BRANCH:
        version_path = migrate.CORE_VERSIONS
    else:
        spec = next((s for s in specs if s.id == args.branch), None)
        if spec is None or spec.migrations_path is None:
            print(f"unknown module id or module has no migrations_path: {args.branch}")
            return 1
        version_path = spec.migrations_path

    if args.autogenerate:
        migrate.upgrade_all(engine, specs)

    command.revision(
        cfg,
        message=args.message,
        autogenerate=args.autogenerate,
        head=f"{args.branch}@head",
        version_path=version_path.as_posix(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
