"""Report Export (PRD 4.1 screen 14): run picker, preview, HTML and PDF export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dfr.core.contracts import Diagnostic, Severity
from dfr.core.db.repos import RunRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.viewmodels.shell import ShellViewModel, StepStatus

SCREEN = ScreenSpec(id="report", title="Report", step="report", order=70, requires=("m11_report",))

try:  # QtWebEngine is large and optional at runtime; the screen degrades to HTML-only without it.
    from PySide6.QtWebEngineWidgets import QWebEngineView

    HAVE_WEBENGINE = True
except ImportError:  # pragma: no cover - depends on the installed Qt modules
    QWebEngineView = None  # type: ignore[assignment, misc]
    HAVE_WEBENGINE = False


class ReportScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        self.html = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        bar.addWidget(heading("Report", "title"))
        bar.addStretch(1)
        bar.addWidget(QLabel("Run"))
        self.runs = QComboBox()
        self.runs.setMinimumWidth(160)
        bar.addWidget(self.runs)
        self.preview_btn = QPushButton("Build preview")
        self.preview_btn.clicked.connect(self.build)
        self.html_btn = QPushButton("Export HTML…")
        self.html_btn.clicked.connect(self.export_html)
        self.pdf_btn = QPushButton("Export PDF…")
        self.pdf_btn.setProperty("accent", True)
        self.pdf_btn.clicked.connect(self.export_pdf)
        self.pdf_btn.setEnabled(HAVE_WEBENGINE)
        if not HAVE_WEBENGINE:
            self.pdf_btn.setToolTip("PDF export needs PySide6 QtWebEngine")
        for b in (self.preview_btn, self.html_btn, self.pdf_btn):
            bar.addWidget(b)
        layout.addLayout(bar)
        self.status = QLabel(
            "Pick a run and build the preview. Every number carries a T1/T2 badge and a source tag."
        )
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.view = (
            QWebEngineView()
            if HAVE_WEBENGINE
            else QLabel("Preview needs QtWebEngine; HTML export still works.")
        )
        layout.addWidget(self.view, 1)
        vm.design_version_id.changed.connect(lambda _: self.reload_runs())
        vm.workspace.changed.connect(lambda what: self.reload_runs() if what == "run" else None)
        self.reload_runs()

    def reload_runs(self) -> None:
        self.runs.clear()
        vid = self.vm.design_version_id.value
        if vid is None:
            return
        for r in RunRepo(self.vm.session, self.vm.clock).for_version(vid):
            label = f"#{r.id}  T{int(r.tier_level)}  {r.status.value}" + (
                f"  (parent #{r.parent_run_id})" if r.parent_run_id else ""
            )
            self.runs.addItem(label, r.id)
        self.runs.setCurrentIndex(self.runs.count() - 1)

    def _run_id(self) -> int | None:
        data = self.runs.currentData()
        return int(data) if data is not None else None

    def build(self) -> str:
        run_id = self._run_id()
        if run_id is None:
            self.status.setText("No run to report on yet.")
            return ""
        try:
            self.html = self.vm.registry.service("build_report_html")(
                self.vm.session, self.vm.registry, run_id, clock=self.vm.clock
            )
        except Exception as exc:
            self.vm.post(
                Diagnostic(
                    code="UI_REPORT_FAILED", severity=Severity.ERROR, module="ui", message=repr(exc)
                )
            )
            self.status.setText("Report build failed; see Messages.")
            return ""
        if HAVE_WEBENGINE and isinstance(self.view, QWebEngineView):
            self.view.setHtml(self.html, QUrl("about:blank"))
        self.status.setText(f"Report for run #{run_id} built ({len(self.html) // 1024} KB).")
        self.vm.set_step("report", StepStatus.DONE)
        return self.html

    def export_html(self) -> None:
        if not self.html and not self.build():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export HTML report", "dfr_report.html", "HTML (*.html)"
        )
        if path:
            Path(path).write_text(self.html, encoding="utf-8")
            self.status.setText(f"HTML written to {path}")

    def export_pdf(self) -> None:
        if not HAVE_WEBENGINE or not isinstance(self.view, QWebEngineView):
            return
        if not self.html and not self.build():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF report", "dfr_report.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(12, 12, 12, 12),
        )
        self.view.page().printToPdf(path, layout)
        self.status.setText(f"PDF written to {path}")


def build(vm: ShellViewModel) -> QWidget:
    return ReportScreen(vm)
