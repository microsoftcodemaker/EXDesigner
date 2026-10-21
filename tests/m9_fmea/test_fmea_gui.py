"""pytest-qt: Design C end to end with M9 -- rows persisted, overrides survive a re-run, CSV and
report section (FME-01..03)."""

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


def test_fmea_screen_override_survives_rerun(qtbot, clock) -> None:
    vm = ShellViewModel(registry=discover(entry_points=False), clock=clock)
    w = MainWindow(vm)
    qtbot.addWidget(w)
    w.open_screen("fmea")
    scr = w._open["fmea"]
    assert "No FMEA yet" in scr.summary.text()
    ws = vm.workspace
    ws.import_files("Design C", FIX / "design_c.BomDoc", FIX / "design_c_protel.net", "buck")
    ws.run_match("buck_integrated")
    ws.confirm([])
    ws.set_spec(
        ConverterSpec(vin_min=7, vin_max=22, vout=3.3, iout_max=3.25, fsw=400e3, t_ambient=20), {}
    )
    assert ws.run_tier1().ok
    assert scr.table.topLevelItemCount() == len(scr.rows) > 50
    # Design C has no rates or lives: every O is the conservative 10 (stated)
    assert all(r.occurrence == 10 and r.occurrence_basis == "no_data" for r in scr.rows)

    target = next(r for r in scr.rows if r.mode_id == "ds_short")
    scr.save_override(target, 5, 2, None, "fused upstream")
    shown = next(r for r in scr.rows if (r.part_id, r.mode_id) == (target.part_id, "ds_short"))
    assert shown.severity == 5 and shown.occurrence == 2 and shown.source_flags["D"] == "seed"

    out = ws.rerun()
    assert out is not None and out.ok
    stored = vm.registry.service("load_fmea_rows")(vm.session, out.run.id)
    again = next(r for r in stored if (r.part_id, r.mode_id) == (target.part_id, "ds_short"))
    assert again.rpn == 5 * 2 * target.detection and again.source_flags["O"] == "user"
    assert again.mitigation_note == "fused upstream"
    assert "fused upstream" in scr.csv_text()

    if vm.registry.has_service("build_report_html"):  # M11 may be absent (subtractive run)
        build = vm.registry.service("build_report_html")
        html = build(vm.session, vm.registry, out.run.id, clock=clock)
        assert "FMEA (component level)" in html and "O = 10" in html
    vm.close()
