"""Circuit Review (PRD 4.1 screen 4): topology, pinouts, roles/rails proposal, confirm."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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

from dfr.core.contracts import PinoutRequest, RoleEdit
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.tokens import PALETTES
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(
    id="circuit", title="Circuit Review", step="circuit", order=30, requires=("m12_topology",)
)
ROLE_COL, RAIL_COL = 1, 2


class CircuitScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:  # noqa: PLR0915 - widget tree
        super().__init__()
        self.vm = vm
        self.ws = vm.workspace
        self._edits: dict[str, RoleEdit] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(heading("Circuit Review", "title"))

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Topology"))
        self.topology = QComboBox()
        self.topology.addItems(self.ws.topologies())
        bar.addWidget(self.topology)
        self.candidate = QComboBox()
        self.candidate.setMinimumWidth(220)
        self.candidate.currentIndexChanged.connect(self._candidate_changed)
        bar.addWidget(QLabel("Candidate stage"))
        bar.addWidget(self.candidate)
        self.match_btn = QPushButton("Match")
        self.match_btn.clicked.connect(self.do_match)
        self.confirm_btn = QPushButton("Confirm roles and rails")
        self.confirm_btn.setProperty("accent", True)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.do_confirm)
        bar.addWidget(self.match_btn)
        bar.addStretch(1)
        bar.addWidget(self.confirm_btn)
        layout.addLayout(bar)

        self.status = QLabel("Import a design, pick the topology, then Match.")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Rails"))
        self.rails = QTreeWidget()
        self.rails.setHeaderLabels(["Rail", "Net"])
        self.rails.setRootIsDecorated(False)
        ll.addWidget(self.rails)
        ll.addWidget(QLabel("Roles (double-click a role to edit; edits are marked user)"))
        self.roles = QTreeWidget()
        self.roles.setHeaderLabels(["Part", "Role", "Rail", "Confidence", "Evidence"])
        self.roles.setRootIsDecorated(False)
        self.roles.setAlternatingRowColors(True)
        self.roles.itemDoubleClicked.connect(self._edit_role)
        self.roles.itemSelectionChanged.connect(self._role_selected)
        ll.addWidget(self.roles, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(
            QLabel("Pinouts needed (prefilled from structure, marked inferred; confirm or edit)")
        )
        self.pinouts = QTreeWidget()
        self.pinouts.setHeaderLabels(["Part", "MPN", "Pins"])
        self.pinouts.setRootIsDecorated(False)
        self.pinouts.itemDoubleClicked.connect(self._enter_pinout)
        rl.addWidget(self.pinouts, 1)
        self.evidence = QTreeWidget()
        self.evidence.setHeaderLabels(["Constraint", "Evidence"])
        self.evidence.setRootIsDecorated(False)
        rl.addWidget(QLabel("Constraint evidence for the chosen candidate"))
        rl.addWidget(self.evidence, 1)
        split.addWidget(right)
        split.setSizes([700, 500])
        layout.addWidget(split, 1)

        self.ws.changed.connect(self._ws_changed)
        self._ws_changed("init")

    # ----------------------------------------------------------------- actions
    def do_match(self) -> None:
        self._edits.clear()
        self.ws.run_match(self.topology.currentText())

    def _candidate_changed(self, index: int) -> None:
        if index >= 0 and self.ws.match is not None and index < len(self.ws.match.candidates):
            chosen = self.ws.match.candidates[index]
            if self.ws.match.proposal is None or self.ws.match.proposal.rails[
                0
            ].net_name != chosen.rails.get(self.ws.match.proposal.rails[0].rail):
                self.ws.run_match(self.topology.currentText(), chosen_index=index)

    def do_confirm(self) -> None:
        stage = self.ws.confirm(list(self._edits.values()))
        if stage is not None:
            self.status.setText(
                f"Confirmed stage {stage.pattern_id} (confidence {stage.match_confidence:.2f}). "
                "Conditions step is ready."
            )
            self.confirm_btn.setEnabled(False)

    # ----------------------------------------------------------------- rendering
    def _ws_changed(self, what: str) -> None:
        if what in ("imported", "reloaded", "init"):
            self.topology.blockSignals(True)
            self.topology.clear()
            self.topology.addItems(self.ws.topologies())
            if self.ws.imported is not None and self.ws.imported.design_id is not None:
                from dfr.core.db.repos import DesignRepo  # noqa: PLC0415

                d = DesignRepo(self.vm.session, self.vm.clock).get(self.ws.imported.design_id)
                if d is not None and d.topology_template:
                    self.topology.setCurrentText(d.topology_template)
            self.topology.blockSignals(False)
        self._render_pinouts()
        if what == "matched":
            self._render_match()
        if what == "confirmed":
            self.confirm_btn.setEnabled(False)

    def _render_pinouts(self) -> None:
        self.pinouts.clear()
        for q in self.ws.pinout_requests:
            item = QTreeWidgetItem([q.refdes, q.mpn or "-", ",".join(q.pin_ids)])
            item.setData(0, Qt.ItemDataRole.UserRole, q.refdes)
            self.pinouts.addTopLevelItem(item)
        for i in range(3):
            self.pinouts.resizeColumnToContents(i)

    def _render_match(self) -> None:
        m = self.ws.match
        palette = PALETTES[self.vm.palette_name.value]
        self.rails.clear()
        self.roles.clear()
        self.evidence.clear()
        self.candidate.blockSignals(True)
        self.candidate.clear()
        if m is not None:
            for i, c in enumerate(m.candidates):
                self.candidate.addItem(
                    f"#{i + 1}  sw={c.rails.get('sw', '?')}  conf {c.confidence:.2f}"
                )
        self.candidate.blockSignals(False)
        if m is None or m.proposal is None:
            self.status.setText(
                "No stage matched. Unmet constraints are listed in Messages; assign roles manually "
                "by double-clicking parts once a proposal exists, or choose another topology."
            )
            self.confirm_btn.setEnabled(False)
            return
        p = m.proposal
        low = p.confidence < 0.7
        self.status.setText(
            f"{p.pattern_id}: confidence {p.confidence:.2f}"
            + ("  — below 0.7, review every role" if low else "")
            + f". {len(m.candidates)} candidate stage(s). Edit any role, then Confirm."
        )
        for r in p.rails:
            self.rails.addTopLevelItem(QTreeWidgetItem([r.rail, r.net_name]))
        for a in sorted(p.assignments, key=lambda a: (a.role == "other", a.refdes)):
            edit = self._edits.get(a.refdes)
            role = edit.role if edit else a.role
            rail = (edit.rail if edit else a.rail) or ""
            item = QTreeWidgetItem([a.refdes, role, rail, f"{a.confidence:.2f}", a.evidence])
            item.setData(0, Qt.ItemDataRole.UserRole, a.refdes)
            if edit:
                item.setForeground(ROLE_COL, QColor(palette.tier.tier2))
                item.setToolTip(ROLE_COL, "user edit")
            elif low or a.confidence < 0.7:
                item.setForeground(ROLE_COL, QColor(palette.status.warn))
            self.roles.addTopLevelItem(item)
        best = m.candidates[
            self.candidate.currentIndex() if self.candidate.currentIndex() >= 0 else 0
        ]
        for e in best.evidence:
            item = QTreeWidgetItem([e.constraint, e.evidence])
            item.setForeground(
                0, QColor(palette.status.pass_ if e.satisfied else palette.status.fail)
            )
            self.evidence.addTopLevelItem(item)
        for tree, n in ((self.rails, 2), (self.roles, 5), (self.evidence, 2)):
            for i in range(n):
                tree.resizeColumnToContents(i)
        self.confirm_btn.setEnabled(True)

    def _role_selected(self) -> None:
        items = self.roles.selectedItems()
        if not items or self.ws.match is None or self.ws.match.proposal is None:
            return
        refdes = items[0].data(0, Qt.ItemDataRole.UserRole)
        a = next((x for x in self.ws.match.proposal.assignments if x.refdes == refdes), None)
        if a is not None:
            self.vm.select(
                Selection(
                    "role",
                    f"{a.refdes}: {a.role}",
                    [
                        ("Role", a.role),
                        ("Rail", a.rail or "-"),
                        ("Confidence", f"{a.confidence:.2f}"),
                        ("Provenance", a.provenance.value),
                        ("Evidence", a.evidence),
                    ],
                    payload=a,
                )
            )

    def _edit_role(self, item: QTreeWidgetItem, _col: int) -> None:
        m = self.ws.match
        if m is None or m.proposal is None:
            return
        refdes = item.data(0, Qt.ItemDataRole.UserRole)
        patterns: dict[str, Any] = {}
        for provider in self.vm.registry.services_named("topology.patterns"):
            patterns.update(provider())
        pattern = patterns.get(m.topology)
        roles = list(pattern.roles) if pattern else ["other"]
        rails = [r.rail for r in m.proposal.rails]
        dlg = RoleDialog(self, refdes, roles, rails, item.text(ROLE_COL), item.text(RAIL_COL))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._edits[refdes] = RoleEdit(
                refdes=refdes, role=dlg.role.currentText(), rail=dlg.rail.currentText() or None
            )
            self._render_match()

    def _enter_pinout(self, item: QTreeWidgetItem, _col: int) -> None:
        refdes = item.data(0, Qt.ItemDataRole.UserRole)
        q = next((r for r in self.ws.pinout_requests if r.refdes == refdes), None)
        if q is None:
            return
        inferred = dict(q.inferred)
        if self.ws.match is not None:
            inferred.update(self.ws.match.inferred_pins.get(refdes, {}))
        dlg = PinoutDialog(self, q, inferred)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.ws.answer_pinout(refdes, dlg.values())


class RoleDialog(QDialog):
    def __init__(  # noqa: PLR0917
        self, parent: QWidget, refdes: str, roles: list[str], rails: list[str], role: str, rail: str
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Role for {refdes}")
        form = QFormLayout(self)
        self.role = QComboBox()
        self.role.addItems(roles)
        self.role.setCurrentText(role)
        self.rail = QComboBox()
        self.rail.addItems(["", *rails])
        self.rail.setCurrentText(rail)
        form.addRow("Role", self.role)
        form.addRow("Rail", self.rail)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class PinoutDialog(QDialog):
    """One line per pin, prefilled with the structural inference (marked inferred)."""

    def __init__(self, parent: QWidget, req: PinoutRequest, inferred: dict[str, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Pinout for {req.refdes} ({req.mpn or req.libref or 'unknown part'})")
        form = QFormLayout(self)
        note = QLabel(
            "Prefilled entries are inferred from connectivity and are not used until you confirm."
        )
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        form.addRow(note)
        self.edits: dict[str, QLineEdit] = {}
        for pin in req.pin_ids:
            e = QLineEdit(inferred.get(pin, ""))
            e.setPlaceholderText("inferred" if pin in inferred else "e.g. gate / drain / sw / gnd")
            self.edits[pin] = e
            form.addRow(f"Pin {pin}", e)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, str]:
        return {pin: e.text().strip() for pin, e in self.edits.items() if e.text().strip()}


def build(vm: ShellViewModel) -> QWidget:
    return CircuitScreen(vm)
