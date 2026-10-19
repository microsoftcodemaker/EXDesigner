"""pytest-qt smoke tests for the shell (skipped when PySide6 is absent; marked ``gui``)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.gui

from dfr.core.registry import discover  # noqa: E402
from dfr.ui.shell.main_window import MainWindow  # noqa: E402
from dfr.ui.shell.theme import build_qss  # noqa: E402
from dfr.ui.tokens import DARK, LIGHT  # noqa: E402
from dfr.ui.viewmodels.shell import ShellViewModel  # noqa: E402


@pytest.fixture
def window(qtbot, clock):
    vm = ShellViewModel(registry=discover(entry_points=False), clock=clock)
    w = MainWindow(vm)
    qtbot.addWidget(w)
    w.show()
    yield w
    vm.close()


def test_shell_opens_with_panels_and_home_tab(window) -> None:
    assert window.tabs.count() == 1 and window.tabs.tabText(0) == "Designs"
    assert {d.windowTitle() for d in (window.project, window.properties, window.messages)} == {
        "Project",
        "Properties",
        "Messages",
    }
    assert window.project.tree.topLevelItemCount() == 7  # the stepper
    assert "home" in window.screens


def test_theme_toggle_reapplies_stylesheet(window, qtbot) -> None:
    from PySide6.QtWidgets import QApplication

    window.vm.toggle_palette()
    assert window.palette_.name == "light"
    assert LIGHT.canvas in QApplication.instance().styleSheet()
    window.vm.toggle_palette()
    assert DARK.canvas in QApplication.instance().styleSheet()


def test_new_design_flow_updates_status_and_properties(window, qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Board X", True)))
    home = window.tabs.widget(0)
    home.new_design()
    assert window.vm.design_id.value is not None
    assert window.status_design.text().startswith("Board X")
    assert window.properties.title.text() == "Board X"
    assert home.tree.topLevelItemCount() == 1


def test_qss_has_no_unresolved_placeholders() -> None:
    qss = build_qss(DARK)
    assert "{p." not in qss and "None" not in qss
