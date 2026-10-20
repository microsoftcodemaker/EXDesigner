"""Refinement Queue (PRD 4.1 screen 9): ranked triage items with reasons, waive / un-waive,
Values Needed answered by typed entry or Tier 2 CSV, re-run and mark final (PRD 2.6)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.contracts import Part, RefinementItem, SessionState, ValuePrompt
from dfr.core.db.repos import PartRepo, StressRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.screens.stress.screen import AnswerDialog
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(id="refine", title="Refine", step="refine", order=60, requires=("m3_triage",))
COLS = ["#", "Part", "Score", "Status", "Flags", "Parameters", "Scenarios", "Reasons", "Waiver"]
STATE_TEXT = {
    SessionState.DRAFT: "Draft: import a design and confirm the circuit.",
    SessionState.CIRCUIT_CONFIRMED: "Circuit confirmed: run Tier 1 on the Results screen.",
    SessionState.T1_RUNNING: "Running…",
    SessionState.TRIAGED: "Triaged: answer prompts or import Tier 2 values, then re-run; "
    "or mark final.",
    SessionState.T2_QUEUED: "Tier 2 values queued: re-run to update results.",
    SessionState.T2_AWAITING_INPUT: "Waiting for Tier 2 input.",
    SessionState.RERUN: "Re-running…",
    SessionState.FINAL: "Final: results frozen for the report.",
}


class RefineScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:  # noqa: PLR0915 - widget tree
        super().__init__()
        self.vm = vm
        self.ws = vm.workspace
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        bar.addWidget(heading("Refinement queue", "title"))
        bar.addStretch(1)
        self.csv_btn = QPushButton("Import Tier 2 CSV…")
        self.csv_btn.setToolTip(
            "Columns: refdes,param,stat,scenario,value,unit,source,tool,note; "
            "source is measured or simulated"
        )
        self.csv_btn.clicked.connect(self.pick_csv)
        self.rerun_btn = QPushButton("Re-run (Tier 2)")
        self.rerun_btn.setProperty("accent", True)
        self.rerun_btn.clicked.connect(self.do_rerun)
        self.final_btn = QPushButton("Mark final")
        self.final_btn.clicked.connect(self.ws.mark_final)
        for b in (self.csv_btn, self.rerun_btn, self.final_btn):
            bar.addWidget(b)
        layout.addLayout(bar)
        self.state = QLabel()
        self.state.setProperty("role", "muted")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)

        split = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Ranked by score = w1·margin + w2·thermal + w4·blind spot (PRD 3.3)"))
        row.addStretch(1)
        self.waive_btn = QPushButton("Waive selected…")
        self.waive_btn.clicked.connect(self.waive_selected)
        self.unwaive_btn = QPushButton("Un-waive selected")
        self.unwaive_btn.clicked.connect(self.unwaive_selected)
        row.addWidget(self.waive_btn)
        row.addWidget(self.unwaive_btn)
        tl.addLayout(row)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(COLS)
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._selected)
        tl.addWidget(self.table)
        split.addWidget(top)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Values needed (double-click to answer; skipped prompts stay open)"))
        prow.addStretch(1)
        self.skip_btn = QPushButton("Skip selected")
        self.skip_btn.clicked.connect(self.skip_prompt)
        prow.addWidget(self.skip_btn)
        bl.addLayout(prow)
        self.prompts = QTreeWidget()
        self.prompts.setHeaderLabels(
            ["Part", "Parameter", "Stat", "Scenario", "Why", "How to obtain", "Origin"]
        )
        self.prompts.setRootIsDecorated(False)
        self.prompts.itemDoubleClicked.connect(self._answer)
        bl.addWidget(self.prompts)
        split.addWidget(bottom)
        split.setSizes([520, 260])
        layout.addWidget(split, 1)

        vm.workflow_state.changed.connect(lambda _: self._state_text())
        vm.design_version_id.changed.connect(lambda _: self.refresh())
        self.ws.changed.connect(
            lambda what: self.refresh() if what in ("run", "reloaded", "t2_input") else None
        )
        self.refresh()

    # ----------------------------------------------------------------- data
    def _parts(self) -> dict[int, Part]:
        vid = self.vm.design_version_id.value
        if vid is None:
            return {}
        return {p.id: p for p in PartRepo(self.vm.session).for_version(vid) if p.id is not None}

    def _repo(self) -> StressRepo:
        return StressRepo(self.vm.session, self.vm.clock)

    def items(self) -> list[RefinementItem]:
        out = self.ws.last_outcome
        if out is not None and out.context.has("refinement"):
            return list(out.context.get("refinement"))
        run_id = self.vm.current_run_id.value
        if run_id is None or not self.vm.registry.has_service("load_refinement_items"):
            return []
        return list(self.vm.registry.service("load_refinement_items")(self.vm.session, run_id))

    def _state_text(self) -> None:
        state = self.vm.workflow_state.value
        run = self.vm.current_run_id.value
        self.state.setText(
            STATE_TEXT.get(state, state.value) + (f"  (run #{run})" if run is not None else "")
        )
        self.final_btn.setEnabled(run is not None and state is not SessionState.FINAL)
        self.rerun_btn.setEnabled(run is not None and state is not SessionState.FINAL)

    def refresh(self) -> None:
        self._state_text()
        self.table.clear()
        self.prompts.clear()
        parts = self._parts()
        for rank, it in enumerate(self.items(), start=1):
            part = parts.get(it.part_id)
            item = QTreeWidgetItem(
                [
                    str(rank),
                    part.refdes if part else str(it.part_id),
                    f"{it.score:.2f}",
                    it.status,
                    ", ".join(it.flags),
                    ", ".join(it.parameters_to_refine),
                    ", ".join(it.recommended_scenarios),
                    "; ".join(it.reasons),
                    it.waiver_reason or "",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, it.part_id)
            item.setToolTip(7, "\n".join(it.reasons))
            self.table.addTopLevelItem(item)
        for i in range(len(COLS) - 2):
            self.table.resizeColumnToContents(i)
        vid = self.vm.design_version_id.value
        if vid is None:
            return
        for p in self._repo().open_prompts(vid):
            part = parts.get(p.part_id) if p.part_id else None
            row = QTreeWidgetItem(
                [
                    part.refdes if part else "-",
                    p.param,
                    p.stat,
                    p.scenario,
                    p.reason,
                    p.how_to_obtain,
                    p.origin.value,
                ]
            )
            row.setData(0, Qt.ItemDataRole.UserRole, p.id)
            self.prompts.addTopLevelItem(row)
        for i in range(7):
            self.prompts.resizeColumnToContents(i)

    def _current_item(self) -> RefinementItem | None:
        sel = self.table.selectedItems()
        if not sel:
            return None
        pid = int(sel[0].data(0, Qt.ItemDataRole.UserRole))
        return next((i for i in self.items() if i.part_id == pid), None)

    def _selected(self) -> None:
        it = self._current_item()
        if it is None:
            return
        part = self._parts().get(it.part_id)
        rows = [("Score", f"{it.score:.3f}"), ("Status", it.status), ("Flags", ", ".join(it.flags))]
        rows += [(f"Reason {n}", r) for n, r in enumerate(it.reasons, start=1)]
        rows += [
            ("Refine", ", ".join(it.parameters_to_refine) or "-"),
            ("Scenarios", ", ".join(it.recommended_scenarios) or "-"),
            ("Waiver", it.waiver_reason or "-"),
        ]
        title = f"{part.refdes if part else it.part_id} · triage"
        self.vm.select(Selection("refinement", title, rows, payload=it))

    # ----------------------------------------------------------------- actions
    def waive_selected(self) -> None:
        it = self._current_item()
        if it is None:
            return
        flag, ok = QInputDialog.getItem(
            self, "Waive flag", "Flag to waive (takes effect on re-run):", it.flags, 0, False
        )
        if not ok or not flag:
            return
        reason, ok = QInputDialog.getText(self, "Waive flag", "Reason (shown in the report):")
        if ok and reason.strip():
            self.waive(it.part_id, flag, reason.strip())

    def waive(self, part_id: int, flag: str, reason: str) -> None:
        vid = self.vm.design_version_id.value
        if vid is None or not self.vm.registry.has_service("waive_refinement"):
            return
        self.vm.registry.service("waive_refinement")(
            self.vm.session, self.vm.clock, vid, part_id, flag, reason
        )
        self.vm.commit()
        self.ws.note_t2_input()

    def unwaive_selected(self) -> None:
        it = self._current_item()
        vid = self.vm.design_version_id.value
        if it is None or vid is None or not self.vm.registry.has_service("unwaive_refinement"):
            return
        svc = self.vm.registry.service("unwaive_refinement")
        if any(svc(self.vm.session, vid, it.part_id, f) for f in it.flags):
            self.vm.commit()
            self.ws.note_t2_input()

    def pick_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Tier 2 CSV", "", "CSV (*.csv)")
        if path:
            self.import_csv_file(Path(path))

    def import_csv_file(self, path: Path) -> None:
        self.ws.import_t2_csv(path.read_text(encoding="utf-8-sig"), path.name)

    def do_rerun(self) -> None:
        self.ws.rerun()

    def skip_prompt(self) -> None:
        sel = self.prompts.selectedItems()
        if sel:
            self._repo().skip_prompt(int(sel[0].data(0, Qt.ItemDataRole.UserRole)))
            self.vm.commit()
            self.refresh()

    def _prompt(self, prompt_id: int) -> ValuePrompt | None:
        vid = self.vm.design_version_id.value or 0
        return next((p for p in self._repo().open_prompts(vid) if p.id == prompt_id), None)

    def _answer(self, item: QTreeWidgetItem, _col: int) -> None:
        pid = int(item.data(0, Qt.ItemDataRole.UserRole))
        prompt = self._prompt(pid)
        if prompt is None or not self.vm.registry.has_service("answer_prompt"):
            return
        dlg = AnswerDialog(self, prompt)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.entry is None:
            return
        value, unit, source, note = dlg.entry
        self.answer(pid, value, unit, source, note)

    def answer(self, prompt_id: int, value: float, unit: str, source: object, note: str) -> None:
        prompt = self._prompt(prompt_id)
        if prompt is None:
            return
        sv = self.vm.registry.service("answer_prompt")(
            prompt, value, unit, source, note, self.vm.clock
        )
        self._repo().answer_prompt(prompt_id, sv)
        self.vm.commit()
        self.ws.note_t2_input()


def build(vm: ShellViewModel) -> QWidget:
    return RefineScreen(vm)
