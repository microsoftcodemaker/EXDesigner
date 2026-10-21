from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dfr.core.contracts import Part, PartClass, Rating, RatingProvenance, RatingSet
from dfr.core.db import migrate
from dfr.core.db.base import create_sqlite_engine
from dfr.core.db.repos import DesignRepo, PartRepo
from dfr.core.db.session import make_session_factory
from dfr.core.ports import FixedClock
from dfr.core.registry import discover

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 10, 18, 14, 2, 11, tzinfo=UTC)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def specs():
    return discover(entry_points=False).modules


@pytest.fixture
def engine(specs) -> Iterator[Engine]:
    eng = create_sqlite_engine()
    migrate.upgrade_all(eng, specs)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    factory = make_session_factory(engine)
    s = factory()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def design_version_id(session: Session, clock: FixedClock) -> int:
    repo = DesignRepo(session, clock)
    design = repo.create("Design C", topology_template="buck_integrated")
    return repo.new_version(design.id, netlist_format="altium_protel").id


def make_part(refdes: str, part_class: PartClass = PartClass.CAPACITOR, **kw) -> Part:
    ratings = kw.pop("ratings", {})
    return Part(
        refdes=refdes,
        part_class=part_class,
        ratings=RatingSet(
            ratings={
                k: Rating(name=k, value=v, unit=u, provenance=RatingProvenance.SEED)
                for k, (v, u) in ratings.items()
            }
        ),
        **kw,
    )


@pytest.fixture
def parts(session: Session, design_version_id: int) -> list[Part]:
    repo = PartRepo(session)
    return repo.add_many(
        design_version_id,
        [
            make_part("C5", value_si=22e-6, value_unit="F", ratings={"v_rated": (10, "V")}),
            make_part("C6", value_si=22e-6, value_unit="F", ratings={"v_rated": (10, "V")}),
            make_part("L1", PartClass.INDUCTOR, value_si=10e-6, value_unit="H"),
            make_part("U3", PartClass.IC, mpn="LM63635CC3QDRRRQ1"),
            make_part("R9", PartClass.RESISTOR, dnp=True),
        ],
    )


@pytest.fixture(autouse=True)
def _isolated_qsettings(request, tmp_path, monkeypatch) -> None:
    """GUI tests must not write the user's real window layout (HKCU registry)."""
    if "qtbot" not in request.fixturenames:
        return
    from PySide6.QtCore import QSettings

    from dfr.ui.shell import main_window

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        main_window.MainWindow,
        "_settings",
        lambda _self: QSettings(ini, QSettings.Format.IniFormat),
    )


def protel_netlist(components: dict[str, str], nets: dict[str, list[str]]) -> bytes:
    """Synthetic Altium Protel netlist: ``components`` refdes -> comment, ``nets`` name -> pins
    ("Q1-2"). For topologies without a real CAD export (the Design C fixture stays untouched)."""
    lines: list[str] = []
    for ref, comment in components.items():
        lines += ["[", ref, f"FP_{ref}", comment, "", "", "", "]"]
    for name, pins in nets.items():
        lines += ["(", name, *pins, ")"]
    return ("\r\n".join(lines) + "\r\n").encode("latin-1")
