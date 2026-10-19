"""Home / Designs: open, create, list versions and runs (PRD 4.1 screen 1)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.db.repos import DesignRepo, RunRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(id="home", title="Designs", step="design", order=0)


class HomeScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(heading("Designs", "title"))
        hint = QLabel("Create a design, then import its BOM and netlist on the Parts step.")
        hint.setProperty("role", "muted")
        layout.addWidget(hint)

        bar = QHBoxLayout()
        new = QPushButton("New design")
        new.setProperty("accent", True)
        new.clicked.connect(self.new_design)
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self.open_selected)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        bar.addWidget(new)
        bar.addWidget(self.open_btn)
        bar.addWidget(refresh)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Design", "Topology", "Versions", "Runs", "Created"])
        self.tree.setAlternatingRowColors(True)
        self.tree.itemSelectionChanged.connect(self._selected)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_selected())
        layout.addWidget(self.tree, 1)
        self.reload()

    def reload(self) -> None:
        self.tree.clear()
        repo = DesignRepo(self.vm.session, self.vm.clock)
        runs = RunRepo(self.vm.session, self.vm.clock)
        for d in repo.list_all():
            versions = repo.versions(d.id)
            n_runs = sum(len(runs.for_version(v.id)) for v in versions)
            item = QTreeWidgetItem(
                [
                    d.name,
                    d.topology_template or "-",
                    str(len(versions)),
                    str(n_runs),
                    d.created_at.strftime("%Y-%m-%d %H:%M"),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, d.id)
            self.tree.addTopLevelItem(item)
        for i in range(5):
            self.tree.resizeColumnToContents(i)

    def _current_id(self) -> int | None:
        items = self.tree.selectedItems()
        return int(items[0].data(0, Qt.ItemDataRole.UserRole)) if items else None

    def _selected(self) -> None:
        did = self._current_id()
        if did is None:
            return
        repo = DesignRepo(self.vm.session, self.vm.clock)
        d = repo.get(did)
        if d is not None:
            self.vm.select(
                Selection(
                    "design",
                    d.name,
                    [
                        ("Design id", str(d.id)),
                        ("Topology", d.topology_template or "-"),
                        ("Created", d.created_at.isoformat(timespec="seconds")),
                    ],
                    payload=d,
                )
            )

    def open_selected(self) -> None:
        did = self._current_id()
        if did is not None:
            self.vm.open_design(did)

    def new_design(self) -> None:
        name, ok = QInputDialog.getText(self, "New design", "Design name:")
        if not ok or not name.strip():
            return
        repo = DesignRepo(self.vm.session, self.vm.clock)
        d = repo.create(name.strip(), topology_template=None)
        self.vm.commit()
        self.reload()
        self.vm.open_design(d.id)


def build(vm: ShellViewModel) -> QWidget:
    return HomeScreen(vm)
