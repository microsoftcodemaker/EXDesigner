"""Part Review (PRD 4.1 screen 3): fix classification, ratings, DNP. Selection -> Properties."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.contracts import Part, Rating, RatingProvenance
from dfr.core.db.repos import PartRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.viewmodels.shell import Selection, ShellViewModel, StepStatus

SCREEN = ScreenSpec(id="parts", title="Part Review", step="parts", order=20, requires=("m1_bom",))
COLS = ("Refdes", "Class", "Subtype", "Value", "Package", "MPN", "Conf.", "DNP", "Ratings")


class PartsScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        top = QHBoxLayout()
        top.addWidget(heading("Part Review", "title"))
        top.addStretch(1)
        self.filter = QComboBox()
        self.filter.addItems(["All parts", "Needs review (< 0.7)", "DNP"])
        self.filter.currentIndexChanged.connect(lambda _: self.reload())
        self.edit_btn = QPushButton("Edit rating…")
        self.edit_btn.clicked.connect(self.edit_rating)
        self.dnp_btn = QPushButton("Toggle DNP")
        self.dnp_btn.clicked.connect(self.toggle_dnp)
        top.addWidget(self.filter)
        top.addWidget(self.edit_btn)
        top.addWidget(self.dnp_btn)
        layout.addLayout(top)
        hint = QLabel(
            "Ratings carry provenance (seed / BOM description / user). Seed values are generic "
            "class defaults marked verify; missing ratings yield UNKNOWN, never PASS."
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(list(COLS))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.tree, 1)
        vm.design_version_id.changed.connect(lambda _: self.reload())
        vm.workspace.changed.connect(lambda _: self.reload())
        self.reload()

    def _parts(self) -> list[Part]:
        return self.vm.workspace.parts()

    def reload(self) -> None:
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        mode = self.filter.currentIndex()
        for p in self._parts():
            if mode == 1 and p.class_confidence >= 0.7:
                continue
            if mode == 2 and not p.dnp:
                continue
            value = (
                f"{p.value_si:.4g} {p.value_unit or ''}".strip() if p.value_si is not None else ""
            )
            item = QTreeWidgetItem(
                [
                    p.refdes,
                    p.part_class.value,
                    p.subtype or "",
                    value,
                    p.package or "",
                    p.mpn or "",
                    f"{p.class_confidence:.2f}",
                    "yes" if p.dnp else "",
                    str(len(p.ratings.ratings)),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, p.id)
            self.tree.addTopLevelItem(item)
        for i in range(len(COLS)):
            self.tree.resizeColumnToContents(i)
        self.tree.setSortingEnabled(True)

    def _current(self) -> Part | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        pid = items[0].data(0, Qt.ItemDataRole.UserRole)
        return PartRepo(self.vm.session).get(int(pid)) if pid is not None else None

    def _selected(self) -> None:
        p = self._current()
        if p is None:
            return
        rows = [
            ("Class", f"{p.part_class.value} / {p.subtype or '-'}"),
            ("Confidence", f"{p.class_confidence:.2f}"),
            ("MPN", p.mpn or "-"),
            ("Package", p.package or "-"),
            ("Description", p.description or "-"),
        ]
        for k, v in p.attributes.items():
            rows.append((k, v))
        for r in sorted(p.ratings.ratings.values(), key=lambda r: r.name):
            rows.append((f"rating {r.name}", f"{r.value:g} {r.unit}  [{r.provenance.value}]"))
        self.vm.select(Selection("part", p.refdes, rows, payload=p))

    def toggle_dnp(self) -> None:
        p = self._current()
        if p is None or p.id is None:
            return
        PartRepo(self.vm.session).set_dnp(p.id, not p.dnp)
        self.vm.commit()
        self.vm.mark_downstream_stale("parts")
        self.reload()

    def edit_rating(self) -> None:
        p = self._current()
        if p is None or p.id is None:
            return
        dlg = RatingDialog(self, p)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_rating is not None:
            PartRepo(self.vm.session).set_rating(p.id, dlg.result_rating)
            self.vm.commit()
            self.vm.set_step("parts", StepStatus.DONE)
            self.vm.mark_downstream_stale("parts")
            self.reload()
            self._selected()


class RatingDialog(QDialog):
    """Edit or add one rating with user provenance (BOM-07)."""

    def __init__(self, parent: QWidget, part: Part) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Rating for {part.refdes}")
        self.result_rating: Rating | None = None
        form = QFormLayout(self)
        self.name = QComboBox()
        self.name.setEditable(True)
        known = [
            "v_rated",
            "i_rated",
            "i_sat",
            "p_rated",
            "v_ds",
            "i_d",
            "rds_on",
            "tj_max",
            "theta_ja",
            "esr",
            "dcr",
            "i_ripple",
            "v_in_max",
            "i_out",
            "i_limit",
            "eta",
            "qg",
            "t_knee",
            "t_max",
            "vf",
            "turns_ratio",
            "l_primary",
            "v_clamp",
        ]
        self.name.addItems(sorted(set(known) | set(part.ratings.ratings)))
        self.value = QLineEdit()
        self.unit = QLineEdit()
        self.ref = QLineEdit()
        self.ref.setPlaceholderText("datasheet page / source note")
        form.addRow("Rating", self.name)
        form.addRow("Value", self.value)
        form.addRow("Unit", self.unit)
        form.addRow("Source", self.ref)
        self.name.currentTextChanged.connect(lambda name: self._prefill(part, name))
        self._prefill(part, self.name.currentText())
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _prefill(self, part: Part, name: str) -> None:
        r = part.ratings.get(name)
        if r is not None:
            self.value.setText(f"{r.value:g}")
            self.unit.setText(r.unit)
            self.ref.setText(r.provenance_ref or "")

    def _accept(self) -> None:
        try:
            value = float(self.value.text())
        except ValueError:
            self.value.setFocus()
            return
        self.result_rating = Rating(
            name=self.name.currentText().strip(),
            value=value,
            unit=self.unit.text().strip(),
            provenance=RatingProvenance.USER,
            provenance_ref=self.ref.text().strip() or None,
        )
        self.accept()


def build(vm: ShellViewModel) -> QWidget:
    return PartsScreen(vm)
