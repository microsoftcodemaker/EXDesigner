"""pytest-qt: the Tier 1 workflow through the screens (import -> circuit -> conditions -> run)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("dfr.topologies.buck")
pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt  # noqa: E402

from dfr.core.contracts import DeratingStatus, RoleEdit  # noqa: E402
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


def test_screens_discovered_and_gated_by_modules(window) -> None:
    assert set(window.screens) >= {
        "home",
        "import_design",
        "parts",
        "circuit",
        "conditions",
        "results",
    }
    assert all(
        set(e.spec.requires) <= set(window.vm.present_modules) for e in window.screens.values()
    )


def test_full_tier1_flow_through_screens(window) -> None:
    vm = window.vm
    window.open_screen("import_design")
    imp = window._open["import_design"]
    imp.name.setText("Design C")
    imp.bom[1].setText(str(BOM))
    imp.net[1].setText(str(NET))
    imp.do_import()
    assert "28 parts, 19 nets" in imp.summary.text()
    assert imp.requests.topLevelItemCount() == 8
    assert (
        vm.step_status["parts"] is StepStatus.DONE and vm.step_status["circuit"] is StepStatus.READY
    )

    window.open_screen("parts")
    parts = window._open["parts"]
    assert parts.tree.topLevelItemCount() == 28
    parts.tree.setCurrentItem(parts.tree.topLevelItem(0))
    assert vm.selection.value is not None and vm.selection.value.kind == "part"

    window.open_screen("circuit")
    circ = window._open["circuit"]
    assert not circ.confirm_btn.isEnabled()
    circ.topology.setCurrentText("buck_integrated")
    circ.do_match()
    assert "confidence 0.75" in circ.status.text()
    assert circ.candidate.count() == 2
    assert circ.rails.topLevelItemCount() == 4 and circ.roles.topLevelItemCount() == 28
    assert circ.confirm_btn.isEnabled()
    circ._edits["R3"] = RoleEdit(refdes="R3", role="sense_resistor", rail="vout")
    circ.do_confirm()
    assert vm.workspace.stage is not None and vm.step_status["circuit"] is StepStatus.DONE
    assert not circ.confirm_btn.isEnabled()
    rm = vm.registry.service("role_map_for")(vm.session, vm.clock, vm.workspace.stage.id)
    assert rm.parts_with_role("sense_resistor") == ("R3",)

    window.open_screen("conditions")
    cond = window._open["conditions"]
    assert cond.inferred_labels["L"].text().startswith("1e-05 H")
    cond.vin_min.setValue(7)
    cond.vin_max.setValue(22)
    cond.ta.setValue(20)
    cond.iout.setValue(3.25)
    cond.fsw.setValue(400)
    cond.do_apply()
    assert vm.workspace.spec is not None and vm.workspace.spec.fsw == 400e3
    assert vm.step_status["analyze"] is StepStatus.READY

    window.open_screen("results")
    res = window._open["results"]
    res.do_run()
    assert vm.workspace.last_outcome is not None and vm.workspace.last_outcome.ok
    assert "0 FAIL, 2 WARN" in res.summary.text()
    assert res.table.topLevelItemCount() == 9 and res.prompts.topLevelItemCount() == 1
    assert (
        vm.step_status["analyze"] is StepStatus.DONE
        and vm.step_status["report"] is StepStatus.READY
    )
    assert window.status_tier.text() == "Tier mix: T1 38  T2 0  (0% T2)"
    res.table.setCurrentItem(res.table.topLevelItem(0))
    sel = vm.selection.value
    assert sel is not None and sel.kind == "derating" and sel.payload.status is DeratingStatus.WARN

    res.filter.setCurrentText("PASS")
    assert res.table.topLevelItemCount() == 4


def test_conditions_rejects_invalid_spec(window) -> None:
    window.open_screen("conditions")
    cond = window._open["conditions"]
    cond.vin_min.setValue(40)
    cond.vin_max.setValue(24)
    cond.do_apply()
    assert "vin_min" in cond.error.text()
    assert window.vm.workspace.spec is None


def test_stress_table_manual_entry_and_prompt_answer(window) -> None:
    from dfr.core.contracts import Source, Stat

    vm = window.vm
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

    window.open_screen("stress")
    st = window._open["stress"]
    assert st.table.topLevelItemCount() == 38 and st.prompts.topLevelItemCount() == 1
    st.only_effective.setCurrentIndex(1)
    assert st.table.topLevelItemCount() == 38  # all T1 rows are effective so far

    # Answer the IC-loss prompt with a measured value: it becomes a T2 effective row.
    prompt_id = int(st.prompts.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole))
    repo_prompt = next(
        p for p in st._repo().open_prompts(vm.design_version_id.value) if p.id == prompt_id
    )
    sv = vm.registry.service("answer_prompt")(
        repo_prompt, 0.9, "W", Source.MEASURED, "bench", vm.clock
    )
    st._repo().answer_prompt(prompt_id, sv)
    vm.commit()
    st.reload()
    assert st.prompts.topLevelItemCount() == 0
    assert st.table.topLevelItemCount() == 39
    assert (
        window.status_tier.text() == "Tier mix: T1 38  T2 0  (0% T2)"
    )  # status refreshes on refresh_runs
    vm.refresh_runs()
    assert window.status_tier.text() == "Tier mix: T1 38  T2 1  (2% T2)"

    # Manual pinned entry beats the Tier 2 value in the effective set.
    u3 = next(p for p in st._parts().values() if p.refdes == "U3")
    manual = vm.registry.service("manual_stress")(
        u3.id, "p_loss", 0.5, "W", Stat.AVG, vm.clock, scenario="vin_max", pinned=True
    )
    st._repo().add(manual)
    vm.commit()
    st.only_effective.setCurrentIndex(1)
    st.reload()
    eff = {
        (
            st.table.topLevelItem(i).text(0),
            st.table.topLevelItem(i).text(1),
            st.table.topLevelItem(i).text(2),
        ): st.table.topLevelItem(i).text(3)
        for i in range(st.table.topLevelItemCount())
    }
    assert eff[("U3", "p_loss", "vin_max")] == "0.5"
    st.table.setCurrentItem(st.table.topLevelItem(0))
    assert vm.selection.value is not None and vm.selection.value.kind == "stress"
