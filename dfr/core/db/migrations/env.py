"""Alembic environment. Always driven programmatically via ``dfr.core.db.migrate``."""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Engine

import dfr.core.db.models  # noqa: F401  (register core tables on Base.metadata)
from dfr.core.db.base import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine: Engine | None = config.attributes.get("engine")
    if engine is None:
        msg = "Use dfr.core.db.migrate.make_config(engine) to run migrations"
        raise RuntimeError(msg)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE support
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
