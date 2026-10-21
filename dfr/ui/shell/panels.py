"""Dock panels: Project (stepper), Properties (selection), Messages (diagnostics)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.contracts import Diagnostic
from dfr.ui.kit import KeyValueGrid, heading
from dfr.ui.tokens import Palette, status_color
from dfr.ui.viewmodels.shell import STEPS, Selection, ShellViewModel, StepStatus

_STATUS_GLYPH = {
    StepStatus.NOT_STARTED: "○",
    StepStatus.READY: "◔",
    StepStatus.DONE: "●",
    StepStatus.STALE: "◐",
}


def _dock(title: str, widget: QWidget, object_name: str) -> QDockWidget:
    dock = QDockWidget(title)
    dock.setObjectName(object_name)
    dock.setWidget(widget)
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetClosable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
    )
    return dock


class ProjectPanel(QDockWidget):
    """Altium 'Projects'-style tree: the stepper with per-step status; children are screens."""

    def __init__(
        self, vm: ShellViewModel, palette: Palette, on_open: Callable[[str], None]
    ) -> None:
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setMinimumWidth(180)
        super().__init__("Project")
        self.setObjectName("dock_project")
        self.setWidget(self.tree)
        self.vm, self.palette_, self._on_open = vm, palette, on_open
        self._screens_by_step: dict[str, list[tuple[str, str]]] = {}
        vm.steps_changed.connect(lambda _: self.rebuild())
        self.tree.itemActivated.connect(self._activated)
        self.tree.itemClicked.connect(self._activated)

    def set_screens(self, screens: list[tuple[str, str, str]]) -> None:
        """(screen_id, title, step) triples from the screen registry."""
        self._screens_by_step = {}
        for sid, title, step in screens:
            self._screens_by_step.setdefault(step, []).append((sid, title))
        self.rebuild()

    def rebuild(self) -> None:
        self.tree.clear()
        for step, label in STEPS:
            status = self.vm.step_status.get(step, StepStatus.NOT_STARTED)
            item = QTreeWidgetItem([f"{_STATUS_GLYPH[status]}  {label}"])
            item.setData(0, Qt.ItemDataRole.UserRole, ("step", step))
            item.setToolTip(0, f"{label}: {status.value}")
            color = {
                StepStatus.DONE: self.palette_.status.pass_,
                StepStatus.STALE: self.palette_.status.warn,
                StepStatus.READY: self.palette_.text,
                StepStatus.NOT_STARTED: self.palette_.text_disabled,
            }[status]
            item.setForeground(0, QColor(color))
            for sid, title in self._screens_by_step.get(step, []):
                child = QTreeWidgetItem([title])
                child.setData(0, Qt.ItemDataRole.UserRole, ("screen", sid))
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            item.setExpanded(True)

    def _activated(self, item: QTreeWidgetItem, _col: int) -> None:
        kind, key = item.data(0, Qt.ItemDataRole.UserRole)
        if kind == "screen":
            self._on_open(key)
        else:
            screens = self._screens_by_step.get(key, [])
            if screens:
                self._on_open(screens[0][0])


class PropertiesPanel(QDockWidget):
    """Shows whatever is selected anywhere in the workspace (Altium Properties panel)."""

    def __init__(self, vm: ShellViewModel) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        self.title = heading("Nothing selected")
        self.kind = QLabel("")
        self.kind.setProperty("role", "muted")
        self.grid = KeyValueGrid()
        layout.addWidget(self.title)
        layout.addWidget(self.kind)
        layout.addWidget(self.grid)
        layout.addStretch(1)
        super().__init__("Properties")
        self.setObjectName("dock_properties")
        self.setWidget(body)
        vm.selection.changed.connect(self.show_selection)
        self.show_selection(vm.selection.value)

    def show_selection(self, sel: Selection | None) -> None:
        if sel is None:
            self.title.setText("Nothing selected")
            self.kind.setText("")
            self.grid.set_rows([])
            return
        self.title.setText(sel.title)
        self.kind.setText(sel.kind)
        self.grid.set_rows(sel.fields)


class MessagesPanel(QDockWidget):
    """Diagnostics list with severity color and a clear button (Altium Messages panel)."""

    def __init__(self, vm: ShellViewModel, palette: Palette) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setProperty("role", "muted")
        clear = QPushButton("Clear")
        clear.clicked.connect(vm.clear_messages)
        bar.addWidget(self.summary)
        bar.addStretch(1)
        bar.addWidget(clear)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Severity", "Module", "Code", "Message"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        layout.addLayout(bar)
        layout.addWidget(self.tree)
        super().__init__("Messages")
        self.setObjectName("dock_messages")
        self.setWidget(body)
        self.palette_ = palette
        vm.messages_changed.connect(self.show_messages)
        self.show_messages(vm.messages)

    def show_messages(self, diags: list[Diagnostic]) -> None:
        self.tree.clear()
        counts = {"error": 0, "warning": 0, "info": 0}
        for d in diags:
            counts[d.severity.value] = counts.get(d.severity.value, 0) + 1
            item = QTreeWidgetItem([d.severity.value.upper(), d.module or "", d.code, d.message])
            color = status_color(
                self.palette_,
                {"error": "fail", "warning": "warn", "info": "info"}[d.severity.value],
            )
            item.setForeground(0, QColor(color))
            if d.line_no is not None:
                item.setToolTip(3, f"line {d.line_no}")
            self.tree.addTopLevelItem(item)
        for i in range(3):
            self.tree.resizeColumnToContents(i)
        self.summary.setText(
            f"  {counts['error']} errors, {counts['warning']} warnings, {counts['info']} info"
        )
