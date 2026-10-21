"""Failure rate / MTBF (PRD 3.8, MTB-05): per-method system figures side by side, per-part
rates and exclusions of the chosen method, the model-comparison table, and the M8 run settings
(environment, quality) for the next run. MTBF only for constant-rate methods (MTB-04)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.db.repos import PartRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(
    id="reliability",
    title="Failure Rate",
    step="analyze",
    order=52,
    requires=("m8_failure_rate",),
)
HOURS_PER_YEAR = 8766.0
ENV_KEY, QUALITY_KEY = "fr_environment", "fr_quality"
SUMMARY_COLS = [
    "Method",
    "Table",
    "Confidence",
    "λ system",
    "MTBF",
    "MTTF",
    "B10",
    "Parts",
    "Excl.",
]
TABLE_DEFAULT = "(table default)"


def _years(h: float | None) -> str:
    return f"{h / HOURS_PER_YEAR:.3g} y" if h is not None else "n/a"


class ReliabilityScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        self.ws = vm.workspace
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        bar.addWidget(heading("Failure rate and MTBF", "title"))
        bar.addStretch(1)
        self.env = QComboBox()
        self.quality = QComboBox()
        for label, box, key in (
            ("Environment", self.env, ENV_KEY),
            ("Quality", self.quality, QUALITY_KEY),
        ):
            box.setMinimumWidth(140)
            box.setToolTip("Used on the next run; keys come from the imported tables")
            box.currentTextChanged.connect(lambda text, k=key: self._setting(k, text))
            bar.addWidget(QLabel(label))
            bar.addWidget(box)
        layout.addLayout(bar)
        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        split = QSplitter(Qt.Orientation.Vertical)
        self.methods = QTreeWidget()
        self.methods.setHeaderLabels(SUMMARY_COLS)
        self.methods.setRootIsDecorated(False)
        self.methods.itemSelectionChanged.connect(self._fill_parts)
        split.addWidget(self.methods)
        self.parts = QTreeWidget()
        self.parts.setHeaderLabels(["Part", "λ (FIT)", "Share", "Factors / reason"])
        self.parts.setRootIsDecorated(False)
        self.parts.setAlternatingRowColors(True)
        split.addWidget(self.parts)
        self.compare = QTreeWidget()
        self.compare.setRootIsDecorated(False)
        self.compare.setWordWrap(True)
        split.addWidget(self.compare)
        split.setSizes([140, 360, 220])
        layout.addWidget(split, 1)

        self._fill_comparison()
        self._fill_options()
        self.ws.changed.connect(
            lambda what: self.refresh() if what in ("run", "reloaded") else None
        )
        self.refresh()

    # ----------------------------------------------------------------- data
    def results(self) -> list[Any]:
        out = self.ws.last_outcome
        return list(out.context.get_or("failure_rate", [])) if out is not None else []

    def _fill_comparison(self) -> None:
        reg = self.vm.registry
        if not reg.has_service("failure_rate.comparison"):
            return
        header, rows = reg.service("failure_rate.comparison")()
        self.compare.setHeaderLabels(header)
        for row in rows:
            self.compare.addTopLevelItem(QTreeWidgetItem(row))
        for i in range(len(header)):
            self.compare.setColumnWidth(i, 160 if i == 0 else 300)

    def _fill_options(self) -> None:
        reg = self.vm.registry
        opts = (
            reg.service("failure_rate.run_options")()
            if reg.has_service("failure_rate.run_options")
            else {}
        )
        for box, name, key in (
            (self.env, "environment", ENV_KEY),
            (self.quality, "quality", QUALITY_KEY),
        ):
            keys: list[str] = []
            for o in opts.values():
                keys += [k for k in o.get(name, []) if k not in keys]
            box.blockSignals(True)
            box.clear()
            box.addItems([TABLE_DEFAULT, *keys])
            current = self.ws.run_extra.get(key)
            box.setCurrentText(current if current in keys else TABLE_DEFAULT)
            box.setEnabled(bool(keys))
            if not keys:
                box.setToolTip("No table defines this factor yet (shipped 217F/SR-332 are empty)")
            box.blockSignals(False)

    def _setting(self, key: str, text: str) -> None:
        self.ws.set_run_extra(key, None if text == TABLE_DEFAULT else text)

    def refresh(self) -> None:
        self._fill_options()
        self.methods.clear()
        self.parts.clear()
        results = self.results()
        if not results:
            self.summary.setText(
                "No failure-rate results yet: run the analysis (Results screen). Shipped "
                "MIL-HDBK-217F / SR-332 tables are empty until you import your own "
                "(docs/failure_rate_tables.md); PoF needs M7 lifetime estimates."
            )
            return
        n_parts = len(self._part_names())
        for i, r in enumerate(results):
            constant = r.system_lambda_fit is not None
            item = QTreeWidgetItem(
                [
                    r.method,
                    r.table_id or "-",
                    r.confidence.value if r.confidence else "-",
                    f"{r.system_lambda_fit:.4g} FIT" if constant else "-",
                    _years(r.system_mtbf_h) if constant else "-",
                    _years(r.system_mttf_h) if r.system_mttf_h is not None else "-",
                    _years(r.b10_h) if r.b10_h is not None else "-",
                    str(len(r.per_part)),
                    str(len(r.excluded_part_ids)),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            item.setToolTip(0, "\n".join(r.assumptions))
            self.methods.addTopLevelItem(item)
        for i in range(len(SUMMARY_COLS)):
            self.methods.resizeColumnToContents(i)
        self.summary.setText(
            f"{len(results)} method(s) on {n_parts} parts. Methods are never summed together: "
            "constant-rate tables give λ and MTBF, the PoF roll-up gives MTTF and B10 (MTB-04). "
            "Select a method for its per-part rates and exclusions."
        )
        first = self.methods.topLevelItem(0)
        if first is not None:
            self.methods.setCurrentItem(first)

    def _part_names(self) -> dict[int, str]:
        vid = self.vm.design_version_id.value
        return {
            p.id: p.refdes
            for p in (PartRepo(self.vm.session).for_version(vid) if vid else [])
            if p.id is not None
        }

    def _fill_parts(self) -> None:
        self.parts.clear()
        sel = self.methods.selectedItems()
        results = self.results()
        if not sel or not results:
            return
        r = results[int(sel[0].data(0, Qt.ItemDataRole.UserRole))]
        names = self._part_names()
        total = sum(p.lambda_fit for p in r.per_part) or 1.0
        for p in sorted(r.per_part, key=lambda p: -p.lambda_fit):
            factors = ", ".join(f"{k}={v:.3g}" for k, v in p.factors.items())
            self.parts.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        names.get(p.part_id, str(p.part_id)),
                        f"{p.lambda_fit:.4g}",
                        f"{100 * p.lambda_fit / total:.1f}%",
                        factors,
                    ]
                )
            )
        for pid in r.excluded_part_ids:
            self.parts.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        names.get(pid, str(pid)),
                        "excluded",
                        "",
                        r.excluded_reasons.get(pid, "excluded"),
                    ]
                )
            )
        for i in range(3):
            self.parts.resizeColumnToContents(i)
        self.vm.select(
            Selection(
                "failure_rate",
                r.method,
                [
                    ("Table", r.table_id or "-"),
                    *((f"Assumption {n}", a) for n, a in enumerate(r.assumptions, start=1)),
                ],
                payload=r,
            )
        )


def build(vm: ShellViewModel) -> QWidget:
    return ReliabilityScreen(vm)
