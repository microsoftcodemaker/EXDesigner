"""pytest-qt: Refine screen flow (triage list -> answer prompt / CSV / waive -> re-run -> compare)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("dfr.topologies.buck")
pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt  # noqa: E402

from dfr.core.contracts import SessionState, Source  # noqa: E402
from dfr.core.registry import discover  # noqa: E402
from dfr.ui.shell.main_window import MainWindow  # noqa: E402
from dfr.ui.viewmodels.shell import ShellViewModel, StepStatus  # noqa: E402
from tests.conftest import FIXTURES  # noqa: E402

BOM = FIXTURES / "design_c" / "design_c.BomDoc"
NET = FIXTURES / "design_c" / "design_c_protel.net"


@pytest.fixture
def window(qtbot, clock):
    vm = ShellViewModel(registry=discover(entry_points=False), clock=clock)
    w = MainWindow(vm)
    qtbot.addWidget(w)
    w.show()
    yield w
    vm.close()


def _run_tier1(window) -> None:
    window.open_screen("import_design")
    imp = window._open["import_design"]
    imp.bom[1].setText(str(BOM))
    imp.net[1].setText(str(NET))
    imp.do_import()
    window.open_screen("circuit")
    circ = window._open["circuit"]
    circ.do_match()
    circ.do_confirm()
    window.open_screen("conditions")
    cond = window._open["conditions"]
    cond.vin_min.setValue(7)
    cond.vin_max.setValue(22)
    cond.ta.setValue(20)
    cond.iout.setValue(3.25)
    cond.do_apply()
    window.open_screen("results")
    window._open["results"].do_run()


def test_refine_screen_flow(window, tmp_path) -> None:
    vm = window.vm
    assert "refine" in window.screens and "compare" in window.screens
    window.open_screen("refine")
    ref = window._open["refine"]
    assert ref.table.topLevelItemCount() == 0 and "Draft" in ref.state.text()
    assert not ref.rerun_btn.isEnabled() and not ref.final_btn.isEnabled()

    _run_tier1(window)
    assert vm.workflow_state.value is SessionState.TRIAGED
    assert "Triaged" in ref.state.text() and ref.rerun_btn.isEnabled()
    ranked = [ref.table.topLevelItem(i).text(1) for i in range(ref.table.topLevelItemCount())]
    assert ranked == ["U3", "L1", "C2", "C1"]
    assert ref.table.topLevelItem(0).text(4) == "F0, F1, F4:sw_vds_ringing"
    assert ref.prompts.topLevelItemCount() == 5  # 1 from M2 (U3 p_loss) + 4 from M3 blind spots
    origins = {ref.prompts.topLevelItem(i).text(6) for i in range(5)}
    assert origins == {"m2", "m3"}
    ref.table.setCurrentItem(ref.table.topLevelItem(1))
    sel = vm.selection.value
    assert sel is not None and sel.kind == "refinement" and sel.title.startswith("L1")

    # Answer the M3 prompt for L1 i_peak [load_step] with a measured value.
    row = next(
        ref.prompts.topLevelItem(i)
        for i in range(ref.prompts.topLevelItemCount())
        if ref.prompts.topLevelItem(i).text(0) == "L1"
    )
    ref.answer(int(row.data(0, Qt.ItemDataRole.UserRole)), 4.4, "A", Source.MEASURED, "probe")
    assert vm.workflow_state.value is SessionState.T2_QUEUED
    assert vm.step_status["analyze"] is StepStatus.STALE
    assert ref.prompts.topLevelItemCount() == 4

    # Tier 2 CSV from a file: refines L1 i_peak at vin_max (the ind_isat row's stress).
    csv_path = tmp_path / "bench.csv"
    csv_path.write_text(
        "refdes,param,stat,scenario,value,unit,source,tool\nL1,i_peak,peak,vin_max,3.9,A,measured,probe\n",
        encoding="utf-8",
    )
    ref.import_csv_file(csv_path)
    assert vm.tier_mix.value.t2 == 2

    # Waive C1's low-margin flag, then re-run: C1 drops to a waived item and prompts are not repeated.
    c1 = next(p for p in vm.workspace.parts() if p.refdes == "C1")
    ref.waive(c1.id, "F1", "22 V is the absolute maximum of the supply")
    ref.do_rerun()
    assert vm.workflow_state.value is SessionState.TRIAGED
    out = vm.workspace.last_outcome
    assert out is not None and out.ok and out.run.parent_run_id is not None
    rows = {
        ref.table.topLevelItem(i).text(1): ref.table.topLevelItem(i)
        for i in range(ref.table.topLevelItemCount())
    }
    assert rows["C1"].text(3) == "open" and "F4:input_cap_inrush" in rows["C1"].text(4)
    assert "F1" in rows["C1"].text(4) and rows["C1"].text(8).startswith("22 V")
    assert "F4:inductor_isat_load_step" not in rows["L1"].text(4)  # refined by the answer
    assert ref.prompts.topLevelItemCount() == 4

    # Compare Runs defaults to (parent, latest) and shows the refined L1 row as changed.
    window.open_screen("compare")
    cmp_ = window._open["compare"]
    assert cmp_.run_a.count() == 2 and cmp_.run_a.currentData() == out.run.parent_run_id
    assert cmp_.run_b.currentData() == out.run.id
    assert "1 changed row(s) of 9 derating" in cmp_.summary.text()
    cmp_.changed_only.setChecked(True)
    assert cmp_.table.topLevelItemCount() == 1
    changed = cmp_.table.topLevelItem(0)
    assert (changed.text(0), changed.text(1), changed.text(2), changed.text(3)) == (
        "L1",
        "i_peak",
        "3.601",
        "4.4",  # worst scenario per param: the answered load-step peak beats the CSV vin_max row
    )
    assert changed.text(6) == "T1 → T2"
    cmp_.table.setCurrentItem(changed)
    assert vm.selection.value is not None and vm.selection.value.kind == "compare"

    ref.final_btn.click()
    assert vm.workflow_state.value is SessionState.FINAL and "Final" in ref.state.text()
    assert not ref.rerun_btn.isEnabled() and vm.step_status["refine"] is StepStatus.DONE
