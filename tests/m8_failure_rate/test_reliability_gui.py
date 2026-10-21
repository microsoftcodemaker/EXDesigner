"""pytest-qt: Failure Rate screen (MTB-05) on Design C with the shipped (empty) tables."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("dfr.topologies.buck")
pytestmark = pytest.mark.gui

from dfr.core.contracts import ConverterSpec  # noqa: E402
from dfr.core.registry import discover  # noqa: E402
from dfr.ui.shell.main_window import MainWindow  # noqa: E402
from dfr.ui.viewmodels.shell import ShellViewModel  # noqa: E402
from tests.conftest import FIXTURES  # noqa: E402

FIX = FIXTURES / "design_c"


def test_failure_rate_screen(qtbot, clock) -> None:
    vm = ShellViewModel(registry=discover(entry_points=False), clock=clock)
    w = MainWindow(vm)
    qtbot.addWidget(w)
    w.open_screen("reliability")
    scr = w._open["reliability"]
    assert "No failure-rate results yet" in scr.summary.text()
    assert scr.compare.topLevelItemCount() == 6  # PRD 3.8 comparison rows
    # empty shipped tables still name their default lookup keys
    env_keys = [scr.env.itemText(i) for i in range(scr.env.count())]
    assert env_keys[0] == "(table default)" and "GB" in env_keys

    ws = vm.workspace
    ws.import_files("Design C", FIX / "design_c.BomDoc", FIX / "design_c_protel.net", "buck")
    ws.run_match("buck_integrated")
    ws.confirm([])
    ws.set_spec(
        ConverterSpec(vin_min=7, vin_max=22, vout=3.3, iout_max=3.25, fsw=400e3, t_ambient=20), {}
    )
    assert ws.run_tier1().ok
    methods = {
        scr.methods.topLevelItem(i).text(0): scr.methods.topLevelItem(i)
        for i in range(scr.methods.topLevelItemCount())
    }
    pof = {"pof"} if "m7_lifetime" in vm.present_modules else set()  # PoF needs M7 lives
    assert set(methods) == {"mil_hdbk_217f", "sr_332", *pof}
    assert methods["mil_hdbk_217f"].text(3) == "-" and methods["mil_hdbk_217f"].text(8) == "28"
    scr.methods.setCurrentItem(methods["mil_hdbk_217f"])
    assert scr.parts.topLevelItemCount() == 28
    assert scr.parts.topLevelItem(0).text(1) == "excluded"
    assert "no table entry" in scr.parts.topLevelItem(0).text(3)

    ws.set_run_extra("fr_environment", "GB")
    assert ws.run_tier1().run.config.extra["fr_environment"] == "GB"
    vm.close()


def test_run_options_service() -> None:
    reg = discover(entry_points=False)
    opts = reg.service("failure_rate.run_options")()
    assert set(opts) >= {"mil_hdbk_217f", "sr_332", "pof"}
    assert all(set(o) == {"environment", "quality"} for o in opts.values())
