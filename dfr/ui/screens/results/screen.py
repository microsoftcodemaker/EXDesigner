"""Results / Risk Ranking (PRD 4.1 screen 7) with the Run button and the Values Needed list."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.contracts import DeratingStatus
from dfr.core.db.repos import PartRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import MarginBar, StatusChip, TierBadge, heading
from dfr.ui.tokens import PALETTES, status_color
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(
    id="results", title="Results", step="analyze", order=50, requires=("m5_derating",)
)
ORDER = {
    DeratingStatus.FAIL: 0,
    DeratingStatus.WARN: 1,
    DeratingStatus.UNKNOWN: 2,
    DeratingStatus.PASS: 3,
}


class ResultsScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        self.ws = vm.workspace
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        bar.addWidget(heading("Results and risk ranking", "title"))
        bar.addStretch(1)
        self.filter = QComboBox()
        self.filter.addItems(["All", "FAIL", "WARN", "UNKNOWN", "PASS"])
        self.filter.currentIndexChanged.connect(lambda _: self.refresh())
        self.run_btn = QPushButton("Run Tier 1")
        self.run_btn.setProperty("accent", True)
        self.run_btn.clicked.connect(self.do_run)
        bar.addWidget(QLabel("Show"))
        bar.addWidget(self.filter)
        bar.addWidget(self.run_btn)
        layout.addLayout(bar)
        self.summary = QLabel("No run yet. Confirm the circuit, apply conditions, then Run Tier 1.")
        self.summary.setProperty("role", "muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(
            [
                "Part",
                "Parameter",
                "Stress",
                "Limit",
                "Rating",
                "Margin",
                "Status",
                "Tier",
                "Rule",
                "",
            ]
        )
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._selected)
        split.addWidget(self.table)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(
            QLabel("Values needed (Tier 2 prompts; Tier 1 values stay in force until answered)")
        )
        self.prompts = QTreeWidget()
        self.prompts.setHeaderLabels(["Part", "Parameter", "Why", "How to obtain"])
        self.prompts.setRootIsDecorated(False)
        bl.addWidget(self.prompts)
        split.addWidget(bottom)
        split.setSizes([600, 200])
        layout.addWidget(split, 1)
        self.ws.changed.connect(
            lambda what: self.refresh() if what in ("run", "reloaded") else None
        )
        self.refresh()

    def do_run(self) -> None:
        self.ws.run_tier1()

    def refresh(self) -> None:
        self.table.clear()
        self.prompts.clear()
        out = self.ws.last_outcome
        if out is None:
            return
        palette = PALETTES[self.vm.palette_name.value]
        parts = {
            p.id: p
            for p in PartRepo(self.vm.session).for_version(self.vm.design_version_id.value or 0)
        }
        rows = list(out.context.get_or("derating", []))
        counts = {s: sum(r.status is s for r in rows) for s in ORDER}
        thermal = out.context.get_or("thermal", [])
        self.summary.setText(
            f"Run #{out.run.id} {out.run.status.value}: {counts[DeratingStatus.FAIL]} FAIL, "
            f"{counts[DeratingStatus.WARN]} WARN, {counts[DeratingStatus.UNKNOWN]} UNKNOWN, "
            f"{counts[DeratingStatus.PASS]} PASS; {len(thermal)} thermal rows; "
            f"{len(out.context.get_or('stress', []))} stress values (T1). "
            f"Pipeline: {', '.join(out.pipeline.ids)}"
        )
        want = self.filter.currentText()
        effective = out.context.get_or("effective_stress", {})
        tier_by_id = {v.id: int(v.tier) for v in effective.values() if v.id is not None}
        for r in sorted(
            rows, key=lambda r: (ORDER[r.status], r.margin if r.margin is not None else 0)
        ):
            if want != "All" and r.status.value.upper() != want:
                continue
            part = parts.get(r.part_id)
            tier = max((tier_by_id.get(i, 1) for i in r.stress_value_ids), default=1)
            item = QTreeWidgetItem(
                [
                    part.refdes if part else str(r.part_id),
                    r.param,
                    _num(r.stress),
                    _num(r.limit),
                    _num(r.rating),
                    f"{r.margin * 100:.1f}%" if r.margin is not None else "-",
                    "",
                    "",
                    r.rule_id,
                    "",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, (r.part_id, r.rule_id))
            item.setForeground(5, QColor(status_color(palette, r.status.value)))
            self.table.addTopLevelItem(item)
            self.table.setItemWidget(item, 6, StatusChip(r.status.value, palette))
            self.table.setItemWidget(item, 7, TierBadge(tier, palette))
            bar = MarginBar(palette)
            if r.ratio is not None and r.limit:
                bar.set_values(
                    r.ratio if tier == 1 else None,
                    r.ratio if tier == 2 else None,
                    (r.rating / r.limit) if r.rating else 1.0,
                )
            self.table.setItemWidget(item, 9, bar)
        for i in range(9):
            self.table.resizeColumnToContents(i)
        for p in out.context.get_or("prompts", []):
            part = parts.get(p.part_id)
            self.prompts.addTopLevelItem(
                QTreeWidgetItem([part.refdes if part else "-", p.param, p.reason, p.how_to_obtain])
            )
        for i in range(4):
            self.prompts.resizeColumnToContents(i)

    def _selected(self) -> None:
        items = self.table.selectedItems()
        out = self.ws.last_outcome
        if not items or out is None:
            return
        part_id, rule_id = items[0].data(0, Qt.ItemDataRole.UserRole)
        r = next(
            (
                x
                for x in out.context.get_or("derating", [])
                if x.part_id == part_id and x.rule_id == rule_id
            ),
            None,
        )
        part = PartRepo(self.vm.session).get(part_id)
        if r is None or part is None:
            return
        effective = out.context.get_or("effective_stress", {})
        used = [v for v in effective.values() if v.id in r.stress_value_ids]
        rows = [
            ("Status", r.status.value.upper()),
            ("Rule", rule_id),
            ("Stress", _num(r.stress)),
            ("Derated limit", _num(r.limit)),
            ("Rating", _num(r.rating)),
            ("Margin", f"{r.margin * 100:.1f}%" if r.margin is not None else "-"),
        ]
        for v in used:
            rows.append(
                (
                    f"{v.param} [{v.scenario}]",
                    f"{v.value:.4g} {v.unit}  T{int(v.tier)} {v.source.value} "
                    f"{v.tool}  {v.timestamp:%Y-%m-%d %H:%M}",
                )
            )
        for t in out.context.get_or("thermal", []):
            if t.part_id == part_id:
                rows.append(
                    (f"Tj [{t.scenario}]", f"{t.tj:.1f} °C{'  RUNAWAY' if t.runaway_flag else ''}")
                )
        self.vm.select(Selection("derating", f"{part.refdes} · {r.param}", rows, payload=r))


def _num(x: float | None) -> str:
    return f"{x:.4g}" if x is not None else "-"


def build(vm: ShellViewModel) -> QWidget:
    return ResultsScreen(vm)
