"""FMEA (PRD 4.1 screen 12, FME-01..03): generated rows sorted by RPN, filter, edit S/O/D with
persistent overrides (applied on the next run, shown at once), CSV export."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.db.repos import PartRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(id="fmea", title="FMEA", step="analyze", order=58, requires=("m9_fmea",))
COLS = ["Part", "Mode", "System effect", "S", "O", "D", "RPN", "O basis", "Note"]
NUMERIC = (3, 4, 5, 6)


class FmeaScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        self.ws = vm.workspace
        self.rows: list[Any] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        bar.addWidget(heading("FMEA", "title"))
        bar.addStretch(1)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filter by part or mode")
        self.filter.textChanged.connect(lambda _: self._fill())
        self.edit_btn = QPushButton("Edit S/O/D…")
        self.edit_btn.clicked.connect(self.edit_selected)
        self.clear_btn = QPushButton("Clear override")
        self.clear_btn.clicked.connect(self.clear_selected)
        self.csv_btn = QPushButton("Export CSV…")
        self.csv_btn.clicked.connect(self.export_csv)
        for w in (self.filter, self.edit_btn, self.clear_btn, self.csv_btn):
            bar.addWidget(w)
        layout.addLayout(bar)
        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(COLS)
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit_selected())
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 1)
        self.ws.changed.connect(
            lambda what: self.refresh() if what in ("run", "reloaded") else None
        )
        self.refresh()

    # ----------------------------------------------------------------- data
    def _names(self) -> dict[int, str]:
        vid = self.vm.design_version_id.value
        parts = PartRepo(self.vm.session).for_version(vid) if vid else []
        return {p.id: p.refdes for p in parts if p.id is not None}

    def refresh(self) -> None:
        run_id = self.vm.current_run_id.value
        reg = self.vm.registry
        self.rows = (
            list(reg.service("fmea_rows_with_overrides")(self.vm.session, run_id))
            if run_id is not None and reg.has_service("fmea_rows_with_overrides")
            else []
        )
        self._fill()

    def _fill(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.clear()
        names = self._names()
        want = self.filter.text().strip().lower()
        shown = 0
        for i, r in enumerate(self.rows):
            ref = names.get(r.part_id, str(r.part_id))
            if want and want not in ref.lower() and want not in r.mode.lower():
                continue
            user = [k for k, v in sorted(r.source_flags.items()) if v == "user"]
            item = QTreeWidgetItem(
                [
                    ref,
                    r.mode,
                    r.system_effect,
                    "",
                    "",
                    "",
                    "",
                    r.source_flags.get("O", r.occurrence_basis),
                    (f"user: {','.join(user)}  " if user else "") + (r.mitigation_note or ""),
                ]
            )
            for col, v in zip(NUMERIC, (r.severity, r.occurrence, r.detection, r.rpn), strict=True):
                item.setData(col, Qt.ItemDataRole.DisplayRole, v)
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            item.setToolTip(2, f"{r.local_effect}\n{r.system_effect}")
            self.table.addTopLevelItem(item)
            shown += 1
        for c in (0, 1, 3, 4, 5, 6, 7):
            self.table.resizeColumnToContents(c)
        self.table.setColumnWidth(2, 420)
        self.table.setSortingEnabled(True)
        self.table.sortItems(6, Qt.SortOrder.DescendingOrder)
        no_data = sum(r.occurrence_basis == "no_data" for r in self.rows)
        self.summary.setText(
            "No FMEA yet: run the analysis."
            if not self.rows
            else f"{shown} of {len(self.rows)} rows. RPN = S x O x D; O from the M8 rate x mode "
            f"fraction or the M7 life vs target; {no_data} row(s) without either use O = 10 "
            "(conservative). Edits are stored per part and mode, apply on the next run and "
            "survive re-runs. Library values are seed defaults (verify)."
        )

    def _current(self) -> Any | None:
        sel = self.table.selectedItems()
        return self.rows[int(sel[0].data(0, Qt.ItemDataRole.UserRole))] if sel else None

    def _selected(self) -> None:
        r = self._current()
        if r is None:
            return
        fields = [
            ("Mode", r.mode),
            ("Local effect", r.local_effect),
            ("System effect", r.system_effect),
            ("S / O / D", f"{r.severity} / {r.occurrence} / {r.detection}  (RPN {r.rpn})"),
            ("Sources", ", ".join(f"{k}: {v}" for k, v in sorted(r.source_flags.items()))),
            ("λ mode", f"{r.lambda_fit:.4g} FIT" if r.lambda_fit is not None else "-"),
            ("Life / target", f"{r.life_ratio:.3g}" if r.life_ratio is not None else "-"),
        ]
        self.vm.select(Selection("fmea", f"{self._names().get(r.part_id, '?')} · FMEA", fields))

    # ----------------------------------------------------------------- actions
    def edit_selected(self) -> None:
        r = self._current()
        if r is None:
            return
        dlg = SodDialog(self, r)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.save_override(r, *dlg.values())

    def save_override(
        self, r: Any, s: int | None, o: int | None, d: int | None, note: str | None
    ) -> None:
        vid = self.vm.design_version_id.value
        if vid is None:
            return
        self.vm.registry.service("set_fmea_override")(
            self.vm.session,
            self.vm.clock,
            vid,
            r.part_id,
            r.mode_id,
            severity=s,
            occurrence=o,
            detection=d,
            note=note,
        )
        self.vm.commit()
        self.ws.note_t2_input()
        self.refresh()

    def clear_selected(self) -> None:
        r, vid = self._current(), self.vm.design_version_id.value
        if r is None or vid is None:
            return
        if self.vm.registry.service("clear_fmea_override")(
            self.vm.session, vid, r.part_id, r.mode_id
        ):
            self.vm.commit()
            self.ws.note_t2_input()
            self.refresh()

    def csv_text(self) -> str:
        return str(self.vm.registry.service("fmea_csv")(self.rows, self._names()))

    def export_csv(self) -> None:
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export FMEA", "fmea.csv", "CSV (*.csv)")
        if path:
            Path(path).write_text(self.csv_text(), encoding="utf-8")
            self.summary.setText(f"FMEA written to {path}")


class SodDialog(QDialog):
    """S / O / D 1-10; 0 = keep the library (or computed) value."""

    def __init__(self, parent: QWidget, row: Any) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"FMEA: {row.mode}")
        form = QFormLayout(self)
        flags = row.source_flags
        self.spins: list[QSpinBox] = []
        for label, key, value in (
            ("Severity", "S", row.severity),
            ("Occurrence", "O", row.occurrence),
            ("Detection", "D", row.detection),
        ):
            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setSpecialValueText("library / computed")
            spin.setValue(value if flags.get(key) == "user" else 0)
            spin.setToolTip(f"current {value} ({flags.get(key, '')})")
            self.spins.append(spin)
            form.addRow(label, spin)
        self.note = QLineEdit(row.mitigation_note or "")
        self.note.setPlaceholderText("mitigation / reason for the change")
        form.addRow("Note", self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[int | None, int | None, int | None, str | None]:
        s, o, d = (sp.value() or None for sp in self.spins)
        return s, o, d, self.note.text().strip() or None


def build(vm: ShellViewModel) -> QWidget:
    return FmeaScreen(vm)
