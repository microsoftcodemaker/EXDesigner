"""BOM and Netlist Import (PRD 4.1 screen 2): file picks, topology, import, join report."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.db.repos import DesignRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.viewmodels.shell import ShellViewModel

SCREEN = ScreenSpec(
    id="import_design", title="Import BOM + Netlist", step="parts", order=10, requires=("m1_bom",)
)


class ImportScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        self.ws = vm.workspace
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(heading("Import BOM and netlist", "title"))
        hint = QLabel(
            "Supported now: Altium LiveBOM (.BomDoc) and Altium Protel netlist (.net). "
            "Parts are joined by MPN when the BOM has no designators."
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.name = QLineEdit("New design")
        self.bom = self._picker("BOM file (*.BomDoc *.csv)")
        self.net = self._picker("Netlist (*.net)")
        self.topology = QComboBox()
        self.topology.addItems(self.ws.topologies())
        if "buck_integrated" in self.ws.topologies():
            self.topology.setCurrentText("buck_integrated")
        self.into_open = QCheckBox("Import as a new version of the open design")
        self.into_open.setToolTip(
            "Versions are append-only; earlier versions and their runs are kept"
        )
        form.addRow("Design name", self.name)
        form.addRow("", self.into_open)
        form.addRow("BOM", self.bom[0])
        form.addRow("Netlist", self.net[0])
        form.addRow("Topology", self.topology)
        layout.addLayout(form)

        self.run = QPushButton("Import")
        self.run.setProperty("accent", True)
        self.run.clicked.connect(self.do_import)
        row = QHBoxLayout()
        row.addWidget(self.run)
        row.addStretch(1)
        layout.addLayout(row)

        box = QGroupBox("Join report")
        bl = QVBoxLayout(box)
        self.summary = QLabel("Nothing imported yet.")
        self.summary.setProperty("role", "muted")
        self.requests = QTreeWidget()
        self.requests.setHeaderLabels(["Part", "MPN", "Pins", "Why"])
        self.requests.setRootIsDecorated(False)
        bl.addWidget(self.summary)
        bl.addWidget(QLabel("Pinouts the app will ask for on the Circuit step (never guessed):"))
        bl.addWidget(self.requests)
        layout.addWidget(box, 1)
        vm.design_id.changed.connect(lambda _: self._sync_design())
        self._sync_design()

    def _sync_design(self) -> None:
        """With a design open (e.g. just created on Home), import into it by default."""
        did = self.vm.design_id.value
        d = DesignRepo(self.vm.session, self.vm.clock).get(did) if did is not None else None
        self.into_open.setEnabled(d is not None)
        self.into_open.setChecked(d is not None)
        if d is not None:
            self.into_open.setText(f"Import as a new version of the open design {d.name!r}")
            self.name.setText(d.name)

    def _picker(self, filt: str) -> tuple[QWidget, QLineEdit]:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._browse(edit, filt))
        h.addWidget(edit, 1)
        h.addWidget(btn)
        return box, edit

    def _browse(self, edit: QLineEdit, filt: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select file", "", f"{filt};;All files (*)")
        if path:
            edit.setText(path)

    def do_import(self) -> None:
        bom, net = self.bom[1].text().strip(), self.net[1].text().strip()
        if not bom or not net:
            self.summary.setText("Choose both a BOM and a netlist.")
            return
        ok = self.ws.import_files(
            self.name.text().strip() or "Design",
            Path(bom),
            Path(net),
            self.topology.currentText(),
            into_open=self.into_open.isChecked(),
        )
        if not ok or self.ws.imported is None:
            self.summary.setText("Import failed; see Messages.")
            return
        imp = self.ws.imported
        errors = sum(d.severity.value == "error" for d in imp.diagnostics)
        self.summary.setText(
            f"{imp.part_count} parts, {imp.net_count} nets; "
            f"{len(imp.pinout_requests)} pinout requests; "
            f"{errors} errors, {len(imp.diagnostics) - errors} notes (Messages panel)."
        )
        self.requests.clear()
        for q in imp.pinout_requests:
            self.requests.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        q.refdes,
                        q.mpn or "-",
                        ",".join(q.pin_ids),
                        "not in pin-map library",
                    ]
                )
            )
        for i in range(4):
            self.requests.resizeColumnToContents(i)


def build(vm: ShellViewModel) -> QWidget:
    return ImportScreen(vm)
