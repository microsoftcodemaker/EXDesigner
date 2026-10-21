"""pytest-qt: a design reopened in a fresh window restores import context, spec and results."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("dfr.topologies.buck")
pytestmark = pytest.mark.gui

from dfr.core.contracts import ConverterSpec, MissionProfile, Tier  # noqa: E402
from dfr.core.registry import discover  # noqa: E402
from dfr.ui.shell.main_window import MainWindow  # noqa: E402
from dfr.ui.viewmodels.shell import ShellViewModel, StepStatus  # noqa: E402
from tests.conftest import FIXTURES  # noqa: E402

BOM = FIXTURES / "design_c" / "design_c.BomDoc"
NET = FIXTURES / "design_c" / "design_c_protel.net"
SPEC = ConverterSpec(vin_min=7, vin_max=22, vout=3.3, iout_max=3.25, fsw=400e3, t_ambient=20)


def _first_session(db, clock) -> int:
    vm = ShellViewModel(db_path=db, registry=discover(entry_points=False), clock=clock)
    ws = vm.workspace
    assert ws.import_files("Design C", BOM, NET, "buck_integrated")
    ws.run_match("buck_integrated")
    ws.confirm([])
    ws.set_spec(SPEC, {"L": 1.0e-5}, MissionProfile(target_life_years=7))
    assert ws.run_tier1().ok
    design_id = vm.design_id.value
    vm.close()
    assert design_id is not None
    return design_id


def test_reopen_restores_workspace(qtbot, clock, tmp_path) -> None:
    db = tmp_path / "reopen.db"
    design_id = _first_session(db, clock)

    vm = ShellViewModel(db_path=db, registry=discover(entry_points=False), clock=clock)
    w = MainWindow(vm)
    qtbot.addWidget(w)
    for sid in ("circuit", "conditions", "results"):
        w.open_screen(sid)
    vm.open_design(design_id)
    ws = vm.workspace

    assert ws.imported is not None and ws.imported.part_count == 28
    assert ws.stage is not None and ws.spec == SPEC
    assert ws.profile.target_life_years == 7 and ws.spec_overrides == {"L": 1.0e-5}
    assert vm.step_status["conditions"] is StepStatus.DONE

    circ = w._open["circuit"]
    assert "Confirmed stage" in circ.status.text() and circ.roles.topLevelItemCount() == 28
    circ.do_match()  # used to post UI_NO_IMPORT after reopen
    assert ws.match is not None and ws.match.proposal is not None
    assert not any(d.code == "UI_NO_IMPORT" for d in vm.messages)

    cond = w._open["conditions"]
    assert cond.vin_max.value() == 22 and cond.target_years.value() == 7
    assert cond.overrides["L"].text() == "1e-05"

    res = w._open["results"]
    assert "0 FAIL, 2 WARN" in res.summary.text() and res.table.topLevelItemCount() == 9

    if "m3_triage" in vm.present_modules:
        w.open_screen("refine")
        ref = w._open["refine"]
        assert ref.table.topLevelItemCount() >= 4 and ref.rerun_btn.isEnabled()
        parent = vm.current_run_id.value
        out = ws.rerun()  # used to post UI_NOT_READY after reopen
        assert out is not None and out.ok and out.run.parent_run_id == parent
        assert out.run.tier_level is Tier.T2
    vm.close()


def test_import_into_open_design_adds_version(clock, tmp_path) -> None:
    from dfr.core.db.repos import DesignRepo

    vm = ShellViewModel(registry=discover(entry_points=False), clock=clock)
    repo = DesignRepo(vm.session, vm.clock)
    d = repo.create("Board A")
    vm.commit()
    vm.open_design(d.id)
    assert vm.workspace.import_files("ignored", BOM, NET, "buck_integrated", into_open=True)
    assert vm.workspace.import_files("ignored", BOM, NET, "buck_integrated", into_open=True)
    assert [x.name for x in repo.list_all()] == ["Board A"]
    assert len(repo.versions(d.id)) == 2 and vm.design_id.value == d.id
    vm.close()
