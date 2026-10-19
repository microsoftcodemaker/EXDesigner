"""Part catalog (PRD screen 15, pin-map library): datasets, entries, import/export/delete,
and the missing-data report for the open design."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.viewmodels.shell import Selection, ShellViewModel

SCREEN = ScreenSpec(
    id="catalog", title="Part Catalog", step="design", order=5, requires=("m1_bom",)
)


class CatalogScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        bar.addWidget(heading("Part catalog", "title"))
        bar.addStretch(1)
        self.import_btn = QPushButton("Import JSON/CSV…")
        self.import_btn.setProperty("accent", True)
        self.import_btn.clicked.connect(self.do_import)
        self.export_btn = QPushButton("Export JSON…")
        self.export_btn.clicked.connect(self.do_export)
        self.delete_btn = QPushButton("Delete dataset")
        self.delete_btn.clicked.connect(self.do_delete)
        self.missing_btn = QPushButton("Missing data for open design")
        self.missing_btn.clicked.connect(self.show_missing)
        for b in (self.import_btn, self.export_btn, self.delete_btn, self.missing_btn):
            bar.addWidget(b)
        layout.addLayout(bar)
        hint = QLabel(
            "Ratings and pinouts keyed by MPN, consulted at BOM import "
            "(catalog > BOM description > seed). "
            "Re-importing a dataset replaces it; rows edited in the app live in dataset 'user'. "
            "Format: docs/catalog_format.md."
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        layout.addWidget(self.status)

        split = QSplitter(Qt.Orientation.Vertical)
        self.datasets = QTreeWidget()
        self.datasets.setHeaderLabels(
            ["Dataset", "Parts", "Format", "Imported", "File", "Description"]
        )
        self.datasets.setRootIsDecorated(False)
        self.datasets.itemSelectionChanged.connect(self.reload_entries)
        split.addWidget(self.datasets)
        self.entries = QTreeWidget()
        self.entries.setHeaderLabels(
            ["MPN / key", "Class", "Subtype", "Ratings", "Pins", "Dataset"]
        )
        self.entries.setRootIsDecorated(False)
        self.entries.setAlternatingRowColors(True)
        self.entries.setSortingEnabled(True)
        self.entries.itemSelectionChanged.connect(self._entry_selected)
        split.addWidget(self.entries)
        self.missing = QTreeWidget()
        self.missing.setHeaderLabels(["Part", "MPN", "Class", "In catalog", "Missing"])
        self.missing.setRootIsDecorated(False)
        split.addWidget(self.missing)
        split.setSizes([150, 350, 200])
        layout.addWidget(split, 1)
        self.reload()

    # ----------------------------------------------------------------- data
    def _svc(self, name: str) -> Any:
        return self.vm.registry.service(f"catalog.{name}")

    def reload(self) -> None:
        self.datasets.clear()
        for d in self._svc("datasets")(self.vm.session, self.vm.clock):
            when = d["imported_at"].strftime("%Y-%m-%d %H:%M") if d["imported_at"] else "-"
            item = QTreeWidgetItem(
                [
                    d["dataset"],
                    str(d["entries"]),
                    d["format"],
                    when,
                    d["filename"],
                    d["description"],
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, d["dataset"])
            self.datasets.addTopLevelItem(item)
        for i in range(6):
            self.datasets.resizeColumnToContents(i)
        self.reload_entries()

    def _selected_dataset(self) -> str | None:
        items = self.datasets.selectedItems()
        return str(items[0].data(0, Qt.ItemDataRole.UserRole)) if items else None

    def reload_entries(self) -> None:
        self.entries.setSortingEnabled(False)
        self.entries.clear()
        want = self._selected_dataset()
        rows = self._svc("rows")(self.vm.session, self.vm.clock)
        for row in rows:
            if want and row.dataset != want:
                continue
            key = row.mpn or f"{row.libref}@{row.footprint or ''}"
            n_ratings = len(json.loads(row.ratings_json))
            n_pins = len(json.loads(row.pinmap_json))
            item = QTreeWidgetItem(
                [key, row.part_class, row.subtype or "", str(n_ratings), str(n_pins), row.dataset]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, row.id)
            self.entries.addTopLevelItem(item)
        for i in range(6):
            self.entries.resizeColumnToContents(i)
        self.entries.setSortingEnabled(True)
        self.status.setText(
            f"{self.entries.topLevelItemCount()} entries"
            + (f" in dataset {want!r}" if want else "")
        )

    def _entry_selected(self) -> None:
        items = self.entries.selectedItems()
        if not items:
            return
        row_id = int(items[0].data(0, Qt.ItemDataRole.UserRole))
        row = next(
            (r for r in self._svc("rows")(self.vm.session, self.vm.clock) if r.id == row_id), None
        )
        if row is None:
            return
        fields = [
            ("Class", f"{row.part_class} / {row.subtype or '-'}"),
            ("Dataset", row.dataset),
            ("Source", row.source),
        ]
        for name, r in sorted(json.loads(row.ratings_json).items()):
            fields.append(
                (f"rating {name}", f"{r['value']:g} {r['unit']}  — {r.get('provenance_ref') or ''}")
            )
        for pin, fn in sorted(
            json.loads(row.pinmap_json).items(), key=lambda kv: (len(kv[0]), kv[0])
        ):
            fields.append((f"pin {pin}", fn))
        self.vm.select(Selection("catalog", row.mpn or row.libref or "?", fields, payload=row))

    # ----------------------------------------------------------------- actions
    def do_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import catalog", "", "Catalog (*.json *.csv);;All files (*)"
        )
        if not path:
            return
        self.import_path(Path(path))

    def import_path(self, path: Path, dataset: str | None = None) -> bool:
        parsed = self._svc("parse")(path.read_bytes(), path.name, dataset=dataset)
        summary = self._svc("import")(self.vm.session, self.vm.clock, parsed, filename=path.name)
        if summary.diagnostics:
            self.vm.post(*summary.diagnostics)
        if not parsed.ok:
            self.status.setText(f"Import of {path.name} aborted: see Messages (nothing written).")
            return False
        self.vm.commit()
        verb = "replaced" if summary.replaced else "created"
        self.status.setText(
            f"Dataset {summary.dataset!r} {verb}: {summary.entries} parts, "
            f"{summary.ratings} ratings, {summary.pins} pins."
        )
        self.reload()
        return True

    def do_export(self) -> None:
        dataset = self._selected_dataset()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export catalog", f"catalog_{dataset or 'all'}.json", "JSON (*.json)"
        )
        if not path:
            return
        Path(path).write_text(
            self._svc("export")(self.vm.session, self.vm.clock, dataset=dataset), encoding="utf-8"
        )
        self.status.setText(f"Exported {dataset or 'all datasets'} to {path}")

    def do_delete(self) -> None:
        dataset = self._selected_dataset()
        if dataset is None:
            self.status.setText("Select a dataset first.")
            return
        if (
            QMessageBox.question(
                self, "Delete dataset", f"Delete every catalog entry of dataset {dataset!r}?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        n = self._svc("delete_dataset")(self.vm.session, self.vm.clock, dataset)
        self.vm.commit()
        self.status.setText(f"Deleted {n} entries of {dataset!r}.")
        self.reload()

    def show_missing(self) -> None:
        from dfr.app.catalog_report import missing_data  # noqa: PLC0415 - app layer is below ui

        self.missing.clear()
        vid = self.vm.design_version_id.value
        if vid is None:
            self.status.setText("Open a design first.")
            return
        rows = missing_data(self.vm.session, self.vm.registry, vid)
        for r in rows:
            what = list(r.missing_ratings) + (["pinout"] if r.needs_pinout else [])
            self.missing.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        r.refdes,
                        r.mpn or "-",
                        f"{r.part_class}/{r.subtype or '-'}",
                        "yes" if r.in_catalog else "no",
                        ", ".join(what),
                    ]
                )
            )
        for i in range(5):
            self.missing.resizeColumnToContents(i)
        self.status.setText(
            f"{len(rows)} parts need catalog data"
            if rows
            else "Every stressed part has the ratings its rules need and a known pinout."
        )


def build(vm: ShellViewModel) -> QWidget:
    return CatalogScreen(vm)
