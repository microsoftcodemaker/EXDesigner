"""SQLAlchemy base, naming conventions and SQLite engine factory (PRD section 5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names so Alembic autogenerate and SQLite batch mode behave.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

MEMORY_URL = "sqlite+pysqlite:///:memory:"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def sqlite_url(path: Path | str) -> str:
    return f"sqlite+pysqlite:///{Path(path).as_posix()}"


def create_sqlite_engine(url: str = MEMORY_URL, *, echo: bool = False) -> Engine:
    """Engine with foreign keys enforced and WAL journaling for on-disk databases (NFR-11)."""
    engine = create_engine(url, echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        if url != MEMORY_URL:
            cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine
