"""Compare Runs (PRD 4.1 screen 11, UI-03): before/after derating and Tj rows for two runs of
the open design version, with hollow T1 / solid T2 markers on one margin bar."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.contracts import AnalysisRun, DeratingResult, StressValue, ThermalResult
from dfr.core.db.repos import PartRepo, RunRepo, StressRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import MarginBar, StatusChip, heading
from dfr.ui.tokens import PALETTES, status_color
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(
    id="compare", title="Compare Runs", step="refine", order=65, requires=("m5_derating",)
)
COLS = ["Part", "Parameter", "Before", "After", "Margin", "Status", "Tier", "Changed", ""]


@dataclass
class RunData:
    run: AnalysisRun
    derating: dict[tuple[int, str], DeratingResult]
    thermal: dict[int, ThermalResult]
    tier_by_id: dict[int, int]

    def tier_for(self, ids: tuple[int, ...]) -> int:
        return max((self.tier_by_id.get(i, 1) for i in ids), default=1)


class CompareScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        bar.addWidget(heading("Compare runs", "title"))
        bar.addStretch(1)
        self.run_a = QComboBox()
        self.run_b = QComboBox()
        self.changed_only = QCheckBox("Changed rows only")
        for w in (QLabel("Before"), self.run_a, QLabel("After"), self.run_b, self.changed_only):
            bar.addWidget(w)
        layout.addLayout(bar)
        self.summary = QLabel("Open a design with at least one run.")
        self.summary.setProperty("role", "muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(COLS)
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 1)

        self._loading = False
        self.run_a.currentIndexChanged.connect(lambda _: self.refresh())
        self.run_b.currentIndexChanged.connect(lambda _: self.refresh())
        self.changed_only.toggled.connect(lambda _: self.refresh())
        vm.design_version_id.changed.connect(lambda _: self.reload_runs())
        vm.workspace.changed.connect(
            lambda what: self.reload_runs() if what in ("run", "reloaded") else None
        )
        self.reload_runs()

    # ----------------------------------------------------------------- data
    def reload_runs(self) -> None:
        """Fill both pickers; default to (parent of latest, latest) or (first, latest)."""
        self._loading = True
        self.run_a.clear()
        self.run_b.clear()
        vid = self.vm.design_version_id.value
        runs = RunRepo(self.vm.session, self.vm.clock).for_version(vid) if vid else []
        for r in runs:
            label = f"#{r.id}  T{int(r.tier_level)}  {r.status.value}  {r.started_at:%m-%d %H:%M}"
            self.run_a.addItem(label, r.id)
            self.run_b.addItem(label, r.id)
        self._loading = False
        if not runs:
            self.refresh()
            return
        latest = runs[-1]
        before = latest.parent_run_id if latest.parent_run_id is not None else runs[0].id
        self.run_a.setCurrentIndex(self.run_a.findData(before))
        self.run_b.setCurrentIndex(self.run_b.findData(latest.id))
        self.refresh()

    def _load(self, run_id: int) -> RunData | None:
        runs = RunRepo(self.vm.session, self.vm.clock)
        run = runs.get(run_id)
        if run is None:
            return None
        reg = self.vm.registry
        derating = (
            reg.service("load_derating_results")(self.vm.session, run_id)
            if reg.has_service("load_derating_results")
            else []
        )
        thermal = (
            reg.service("load_thermal_results")(self.vm.session, run_id)
            if reg.has_service("load_thermal_results")
            else []
        )
        stress = StressRepo(self.vm.session, self.vm.clock)
        by_id: dict[int, StressValue] = {
            v.id: v for v in stress.for_version(run.design_version_id) if v.id is not None
        }
        tiers = {i: int(by_id[i].tier) for i in runs.effective_ids(run_id).values() if i in by_id}
        worst_tj: dict[int, ThermalResult] = {}
        for t in thermal:
            if t.part_id not in worst_tj or t.tj > worst_tj[t.part_id].tj:
                worst_tj[t.part_id] = t
        return RunData(run, {(r.part_id, r.rule_id): r for r in derating}, worst_tj, tiers)

    def refresh(self) -> None:
        if self._loading:
            return
        self.table.clear()
        a_id, b_id = self.run_a.currentData(), self.run_b.currentData()
        if a_id is None or b_id is None:
            self.summary.setText("Open a design with at least one run.")
            return
        a, b = self._load(int(a_id)), self._load(int(b_id))
        if a is None or b is None:
            return
        palette = PALETTES[self.vm.palette_name.value]
        parts = {
            p.id: p
            for p in PartRepo(self.vm.session).for_version(self.vm.design_version_id.value or 0)
        }
        changed = 0
        keys = sorted(
            set(a.derating) | set(b.derating),
            key=lambda k: (parts[k[0]].refdes if k[0] in parts else "", k[1]),
        )
        for key in keys:
            ra, rb = a.derating.get(key), b.derating.get(key)
            cur = rb or ra
            assert cur is not None
            is_changed = (
                ra is None or rb is None or ra.stress != rb.stress or ra.status is not rb.status
            )
            changed += is_changed
            if self.changed_only.isChecked() and not is_changed:
                continue
            part = parts.get(key[0])
            tier_a = a.tier_for(ra.stress_value_ids) if ra else 1
            tier_b = b.tier_for(rb.stress_value_ids) if rb else 1
            item = QTreeWidgetItem(
                [
                    part.refdes if part else str(key[0]),
                    cur.param,
                    _num(ra.stress) if ra else "—",
                    _num(rb.stress) if rb else "—",
                    f"{_pct(ra.margin if ra else None)} → {_pct(rb.margin if rb else None)}",
                    "",
                    f"T{tier_a} → T{tier_b}",
                    "yes" if is_changed else "",
                    "",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            if rb is not None:
                item.setForeground(4, QColor(status_color(palette, rb.status.value)))
            self.table.addTopLevelItem(item)
            status_txt = f"{ra.status.value if ra else '—'} → {rb.status.value if rb else '—'}"
            chip = StatusChip((rb or ra).status.value, palette)  # type: ignore[union-attr]
            chip.setText(status_txt.upper())
            self.table.setItemWidget(item, 5, chip)
            bar = MarginBar(palette)
            if cur.limit:
                bar.set_values(
                    ra.ratio if ra and ra.ratio is not None else None,
                    rb.ratio if rb and rb.ratio is not None else None,
                    (cur.rating / cur.limit) if cur.rating else 1.0,
                )
            self.table.setItemWidget(item, 8, bar)
        for pid in sorted(set(a.thermal) | set(b.thermal)):
            ta, tb = a.thermal.get(pid), b.thermal.get(pid)
            is_changed = ta is None or tb is None or ta.tj != tb.tj
            changed += is_changed
            if self.changed_only.isChecked() and not is_changed:
                continue
            part = parts.get(pid)
            row = QTreeWidgetItem(
                [
                    part.refdes if part else str(pid),
                    "tj",
                    f"{ta.tj:.1f} °C" if ta else "—",
                    f"{tb.tj:.1f} °C" if tb else "—",
                    "",
                    "",
                    "",
                    "yes" if is_changed else "",
                    "",
                ]
            )
            self.table.addTopLevelItem(row)
        for i in range(len(COLS) - 1):
            self.table.resizeColumnToContents(i)
        self.table.setColumnWidth(len(COLS) - 1, 120)
        self.summary.setText(
            f"Run #{a.run.id} (T{int(a.run.tier_level)}) → run #{b.run.id} "
            f"(T{int(b.run.tier_level)}): {changed} changed row(s) of {len(keys)} derating "
            f"+ {len(set(a.thermal) | set(b.thermal))} thermal."
        )

    def _selected(self) -> None:
        sel = self.table.selectedItems()
        if not sel:
            return
        key = sel[0].data(0, Qt.ItemDataRole.UserRole)
        if key is None:
            return
        a_id, b_id = self.run_a.currentData(), self.run_b.currentData()
        rows = []
        for label, rid in (("Before", a_id), ("After", b_id)):
            data = self._load(int(rid)) if rid is not None else None
            r = data.derating.get(tuple(key)) if data else None
            rows.append(
                (
                    f"{label} (#{rid})",
                    f"{_num(r.stress)} / limit {_num(r.limit)} / {r.status.value.upper()}"
                    if r
                    else "—",
                )
            )
        self.vm.select(Selection("compare", f"{sel[0].text(0)} · {sel[0].text(1)}", rows))


def _num(x: float | None) -> str:
    return f"{x:.4g}" if x is not None else "—"


def _pct(x: float | None) -> str:
    return f"{x * 100:.1f}%" if x is not None else "—"


def build(vm: ShellViewModel) -> QWidget:
    return CompareScreen(vm)
