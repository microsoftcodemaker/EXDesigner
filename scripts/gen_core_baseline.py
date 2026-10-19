"""One-off: autogenerate the core baseline migration against an empty in-memory database.

Usage: python scripts/gen_core_baseline.py
Re-run only when starting the core branch from scratch; later core changes use
``python scripts/new_migration.py core "message"``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import command

from dfr.core.db.base import create_sqlite_engine
from dfr.core.db.migrate import CORE_VERSIONS, make_config

if __name__ == "__main__":
    engine = create_sqlite_engine()
    command.revision(
        make_config(engine),
        message="core baseline",
        autogenerate=True,
        head="base",
        branch_label="core",
        version_path=CORE_VERSIONS.as_posix(),
        rev_id="0001_core",
    )
