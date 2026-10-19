"""Programmatic Alembic driver with one migration branch per module (MOD-05).

Core owns the ``core`` branch under ``dfr/core/db/migrations/versions``. Every module that
declares ``ModuleSpec.migrations_path`` contributes its own branch whose label must equal
the module id. Branches are independent (no ``depends_on``): core is always upgraded first,
then each module branch, so module tables may reference core tables.

Deleting a module folder leaves its version row and tables in existing design files. They
are preserved (reported, never fatal) so re-installing the module resumes its branch;
nothing outside the module folder needs editing (MOD-03).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from dfr.core.registry.spec import ModuleSpec

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
CORE_VERSIONS = MIGRATIONS_DIR / "versions"
CORE_BRANCH = "core"
VERSION_TABLE = "alembic_version"


def module_branches(specs: Iterable[ModuleSpec]) -> list[ModuleSpec]:
    return [s for s in specs if s.migrations_path is not None and s.migrations_path.is_dir()]


def version_locations(specs: Iterable[ModuleSpec] = ()) -> list[Path]:
    locations = [CORE_VERSIONS]
    locations.extend(s.migrations_path for s in module_branches(specs))  # type: ignore[misc]
    return locations


def make_config(engine: Engine, specs: Iterable[ModuleSpec] = ()) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR.as_posix())
    cfg.set_main_option(
        "version_locations", " ".join(p.as_posix() for p in version_locations(specs))
    )
    cfg.set_main_option("path_separator", "space")
    cfg.attributes["engine"] = engine
    return cfg


def orphan_versions(engine: Engine, specs: Iterable[ModuleSpec] = ()) -> list[str]:
    """Version rows for branches whose code is not installed (module folder deleted)."""
    if VERSION_TABLE not in inspect(engine).get_table_names():
        return []
    script = ScriptDirectory.from_config(make_config(engine, specs))
    known = {r.revision for r in script.walk_revisions()}
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT version_num FROM {VERSION_TABLE}")).scalars().all()
    return [str(r) for r in rows if r not in known]


def _stash_orphans(engine: Engine, orphans: list[str]) -> None:
    if not orphans:
        return
    with engine.begin() as conn:
        for rev in orphans:
            conn.execute(text(f"DELETE FROM {VERSION_TABLE} WHERE version_num = :v"), {"v": rev})


def _restore_orphans(engine: Engine, orphans: list[str]) -> None:
    if not orphans:
        return
    with engine.begin() as conn:
        for rev in orphans:
            conn.execute(text(f"INSERT INTO {VERSION_TABLE} (version_num) VALUES (:v)"), {"v": rev})


def upgrade_all(engine: Engine, specs: Iterable[ModuleSpec] = ()) -> list[str]:
    """Apply core, then every present module branch. Returns orphan revision ids (kept).

    Orphan rows are removed only for the duration of the command so Alembic can resolve
    the graph, then written back; a re-installed module resumes its branch where it left off.
    """
    specs = list(specs)
    orphans = orphan_versions(engine, specs)
    _stash_orphans(engine, orphans)
    try:
        cfg = make_config(engine, specs)
        command.upgrade(cfg, f"{CORE_BRANCH}@head")
        for spec in module_branches(specs):
            command.upgrade(cfg, f"{spec.id}@head")
    finally:
        _restore_orphans(engine, orphans)
    return orphans


def downgrade_all(engine: Engine, specs: Iterable[ModuleSpec] = ()) -> None:
    """Module branches first (they reference core tables), then core."""
    specs = list(specs)
    orphans = orphan_versions(engine, specs)
    _stash_orphans(engine, orphans)
    try:
        cfg = make_config(engine, specs)
        for spec in module_branches(specs):
            command.downgrade(cfg, f"{spec.id}@base")
        command.downgrade(cfg, f"{CORE_BRANCH}@base")
    finally:
        _restore_orphans(engine, orphans)


def current_heads(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(MigrationContext.configure(conn).get_current_heads())


def script_heads(engine: Engine, specs: Iterable[ModuleSpec] = ()) -> set[str]:
    return set(ScriptDirectory.from_config(make_config(engine, specs)).get_heads())


def is_up_to_date(engine: Engine, specs: Iterable[ModuleSpec] = ()) -> bool:
    """True when every installed branch head is applied; unknown (orphan) rows are ignored."""
    return script_heads(engine, specs) <= current_heads(engine)
