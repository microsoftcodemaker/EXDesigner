"""Stress Table (PRD 4.1 screen 6): all StressValue rows with source, tier, timestamp and pin;
manual entry (OPC-02); Values Needed panel with typed Tier 2 answers (OPC-13)."""

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
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.contracts import Diagnostic, Part, Severity, Source, Stat, StressValue, ValuePrompt
from dfr.core.db.repos import PartRepo, StressRepo
from dfr.core.db.repos.stress import resolve_effective_stress
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import SourceTag, TierBadge, heading
from dfr.ui.tokens import PALETTES
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(
    id="stress", title="Stress Table", step="analyze", order=55, requires=("m2_conditions",)
)
COLS = [
    "Part",
    "Parameter",
    "Scenario",
    "Value",
    "Unit",
    "Stat",
    "Tier",
    "Source",
    "Tool",
    "Timestamp",
    "Pinned",
    "Effective",
]


class StressScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:  # noqa: PLR0915 - widget tree
        super().__init__()
        self.vm = vm
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        bar.addWidget(heading("Stress values", "title"))
        bar.addStretch(1)
        self.only_effective = QComboBox()
        self.only_effective.addItems(["All rows", "Effective only"])
        self.only_effective.currentIndexChanged.connect(lambda _: self.reload())
        self.manual_btn = QPushButton("Manual entry…")
        self.manual_btn.clicked.connect(self.manual_entry)
        self.pin_btn = QPushButton("Pin / unpin")
        self.pin_btn.setToolTip(
            "A pinned manual value wins over Tier 2 (adds a new pinned copy; rows are immutable)"
        )
        self.pin_btn.clicked.connect(self.toggle_pin)
        bar.addWidget(self.only_effective)
        bar.addWidget(self.manual_btn)
        bar.addWidget(self.pin_btn)
        layout.addLayout(bar)
        hint = QLabel(
            "Precedence: pinned manual > Tier 2 (newest) > Tier 1. Rows are never deleted; "
            "re-runs read "
            "the effective set."
        )
        hint.setProperty("role", "muted")
        layout.addWidget(hint)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(COLS)
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._selected)
        split.addWidget(self.table)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(
            QLabel("Values needed (double-click to answer with a measured or simulated number)")
        )
        row.addStretch(1)
        self.skip_btn = QPushButton("Skip selected")
        self.skip_btn.clicked.connect(self.skip_prompt)
        row.addWidget(self.skip_btn)
        bl.addLayout(row)
        self.prompts = QTreeWidget()
        self.prompts.setHeaderLabels(
            ["Part", "Parameter", "Scenario", "Why", "How to obtain", "Origin"]
        )
        self.prompts.setRootIsDecorated(False)
        self.prompts.itemDoubleClicked.connect(self._answer)
        bl.addWidget(self.prompts)
        split.addWidget(bottom)
        split.setSizes([600, 220])
        layout.addWidget(split, 1)
        vm.design_version_id.changed.connect(lambda _: self.reload())
        vm.workspace.changed.connect(
            lambda what: self.reload() if what in ("run", "reloaded", "t2_input") else None
        )
        self.reload()

    # ----------------------------------------------------------------- data
    def _repo(self) -> StressRepo:
        return StressRepo(self.vm.session, self.vm.clock)

    def _parts(self) -> dict[int, Part]:
        vid = self.vm.design_version_id.value
        return (
            {p.id: p for p in PartRepo(self.vm.session).for_version(vid) if p.id is not None}
            if vid
            else {}
        )

    def reload(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.prompts.clear()
        vid = self.vm.design_version_id.value
        if vid is None:
            return
        palette = PALETTES[self.vm.palette_name.value]
        parts = self._parts()
        values = self._repo().for_version(vid)
        effective_ids = {v.id for v in resolve_effective_stress(values).values()}
        for v in values:
            if self.only_effective.currentIndex() == 1 and v.id not in effective_ids:
                continue
            part = parts.get(v.part_id)
            item = QTreeWidgetItem(
                [
                    part.refdes if part else str(v.part_id),
                    v.param,
                    v.scenario,
                    f"{v.value:.4g}",
                    v.unit,
                    v.stat.value,
                    "",
                    "",
                    v.tool,
                    v.timestamp.strftime("%Y-%m-%d %H:%M"),
                    "pinned" if v.pinned else "",
                    "yes" if v.id in effective_ids else "",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, v.id)
            self.table.addTopLevelItem(item)
            self.table.setItemWidget(item, 6, TierBadge(int(v.tier), palette))
            self.table.setItemWidget(item, 7, SourceTag(v.source.value, palette))
        for i in range(len(COLS)):
            self.table.resizeColumnToContents(i)
        self.table.setSortingEnabled(True)
        for p in self._repo().open_prompts(vid):
            part = parts.get(p.part_id) if p.part_id else None
            item = QTreeWidgetItem(
                [
                    part.refdes if part else "-",
                    p.param,
                    p.scenario,
                    p.reason,
                    p.how_to_obtain,
                    p.origin.value,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, p.id)
            self.prompts.addTopLevelItem(item)
        for i in range(6):
            self.prompts.resizeColumnToContents(i)

    def _current_value(self) -> StressValue | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return self._repo().get(int(items[0].data(0, Qt.ItemDataRole.UserRole)))

    def _selected(self) -> None:
        v = self._current_value()
        if v is None:
            return
        part = self._parts().get(v.part_id)
        self.vm.select(
            Selection(
                "stress",
                f"{part.refdes if part else v.part_id} · {v.param} [{v.scenario}]",
                [
                    ("Value", f"{v.value:.6g} {v.unit} ({v.stat.value})"),
                    ("Tier", f"T{int(v.tier)}"),
                    ("Source", v.source.value),
                    ("Tool", f"{v.tool} {v.tool_version}"),
                    ("Timestamp", v.timestamp.isoformat(timespec="seconds")),
                    ("Pinned", "yes" if v.pinned else "no"),
                    ("Note", v.note or "-"),
                ],
                payload=v,
            )
        )

    # ----------------------------------------------------------------- actions
    def manual_entry(self) -> None:
        parts = self._parts()
        if not parts or not self.vm.registry.has_service("manual_stress"):
            self.vm.post(
                Diagnostic(
                    code="UI_NO_DESIGN",
                    severity=Severity.INFO,
                    module="ui",
                    message="open or import a design first",
                )
            )
            return
        dlg = ManualDialog(self, sorted(parts.values(), key=lambda p: p.refdes))
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.entry is None:
            return
        part_id, param, value, unit, stat, scenario, pinned, note = dlg.entry
        sv = self.vm.registry.service("manual_stress")(
            part_id,
            param,
            value,
            unit,
            stat,
            self.vm.clock,
            scenario=scenario,
            pinned=pinned,
            note=note,
        )
        self._repo().add(sv)
        self.vm.commit()
        self.vm.refresh_runs()
        self.vm.mark_downstream_stale("conditions")
        self.reload()

    def toggle_pin(self) -> None:
        """Rows are immutable: pinning stores a new manual copy with the flag flipped."""
        v = self._current_value()
        if v is None or v.source is not Source.MANUAL:  # only manual rows pin (PRD 3.2 mode b)
            self.vm.post(
                Diagnostic(
                    code="UI_PIN_MANUAL_ONLY",
                    severity=Severity.INFO,
                    module="ui",
                    message="select a manual row to pin; to override a computed value use "
                    "Manual entry… with Pin = yes",
                )
            )
            return
        copy = v.model_copy(
            update={"id": None, "pinned": not v.pinned, "timestamp": self.vm.clock.now()}
        )
        self._repo().add(copy)
        self.vm.commit()
        self.reload()

    def skip_prompt(self) -> None:
        items = self.prompts.selectedItems()
        if items:
            self._repo().skip_prompt(int(items[0].data(0, Qt.ItemDataRole.UserRole)))
            self.vm.commit()
            self.reload()

    def _answer(self, item: QTreeWidgetItem, _col: int) -> None:
        pid = int(item.data(0, Qt.ItemDataRole.UserRole))
        prompt = next(
            (
                p
                for p in self._repo().open_prompts(self.vm.design_version_id.value or 0)
                if p.id == pid
            ),
            None,
        )
        if prompt is None or not self.vm.registry.has_service("answer_prompt"):
            return
        dlg = AnswerDialog(self, prompt)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.entry is None:
            return
        value, unit, source, note = dlg.entry
        sv = self.vm.registry.service("answer_prompt")(
            prompt, value, unit, source, note, self.vm.clock
        )
        self._repo().answer_prompt(pid, sv)
        self.vm.commit()
        self.vm.workspace.note_t2_input()
        self.reload()


class ManualDialog(QDialog):
    def __init__(self, parent: QWidget, parts: list[Part]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manual stress entry")
        self.entry: tuple[int, str, float, str, Stat, str, bool, str | None] | None = None
        form = QFormLayout(self)
        self.part = QComboBox()
        for p in parts:
            self.part.addItem(p.refdes, p.id)
        self.param = QComboBox()
        self.param.setEditable(True)
        self.param.addItems(["i_rms", "i_peak", "v_peak", "v_dc", "p_loss", "i_avg", "t_ambient"])
        self.value = QLineEdit()
        self.unit = QLineEdit("A")
        self.stat = QComboBox()
        self.stat.addItems([s.value for s in Stat])
        self.scenario = QComboBox()
        self.scenario.setEditable(True)
        self.scenario.addItems(["nominal", "vin_max", "vin_min", "startup", "load_step"])
        self.pinned = QComboBox()
        self.pinned.addItems(["no", "yes (wins over Tier 2)"])
        self.note = QLineEdit()
        for label, w in (
            ("Part", self.part),
            ("Parameter", self.param),
            ("Value", self.value),
            ("Unit", self.unit),
            ("Statistic", self.stat),
            ("Scenario", self.scenario),
            ("Pin", self.pinned),
            ("Note", self.note),
        ):
            form.addRow(label, w)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self) -> None:
        try:
            value = float(self.value.text())
        except ValueError:
            self.value.setFocus()
            return
        self.entry = (
            int(self.part.currentData()),
            self.param.currentText().strip(),
            value,
            self.unit.text().strip(),
            Stat(self.stat.currentText()),
            self.scenario.currentText().strip(),
            self.pinned.currentIndex() == 1,
            self.note.text().strip() or None,
        )
        self.accept()


class AnswerDialog(QDialog):
    """Typed Tier 2 answer: value, unit, measured/simulated, tool note (PRD 3.2 mode d)."""

    def __init__(self, parent: QWidget, prompt: ValuePrompt) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Answer: {prompt.param} [{prompt.scenario}]")
        self.entry: tuple[float, str, Source, str] | None = None
        form = QFormLayout(self)
        why = QLabel(f"<b>Why:</b> {prompt.reason}<br><b>How:</b> {prompt.how_to_obtain}")
        why.setWordWrap(True)
        form.addRow(why)
        self.value = QLineEdit()
        self.unit = QLineEdit({"p_loss": "W", "v_peak": "V", "v_dc": "V"}.get(prompt.param, "A"))
        self.source = QComboBox()
        self.source.addItems([Source.MEASURED.value, Source.SIMULATED.value])
        self.note = QLineEdit()
        self.note.setPlaceholderText("tool / instrument, e.g. LTspice 24, Rigol MSO5000")
        form.addRow("Value", self.value)
        form.addRow("Unit", self.unit)
        form.addRow("Source", self.source)
        form.addRow("Tool note", self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self) -> None:
        try:
            value = float(self.value.text())
        except ValueError:
            self.value.setFocus()
            return
        self.entry = (
            value,
            self.unit.text().strip(),
            Source(self.source.currentText()),
            self.note.text().strip(),
        )
        self.accept()


def build(vm: ShellViewModel) -> QWidget:
    return StressScreen(vm)
