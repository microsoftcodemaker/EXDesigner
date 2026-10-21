"""Main window: menu + toolbar, central document tabs, dockable Project / Properties / Messages
panels, status bar with design version, active run and Tier mix (PRD 4.1 navigation).
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QToolBar,
    QWidget,
)

from dfr import __version__
from dfr.ui.screens import ScreenEntry, discover_screens
from dfr.ui.shell.panels import MessagesPanel, ProjectPanel, PropertiesPanel
from dfr.ui.shell.theme import build_qss
from dfr.ui.tokens import PALETTES, Palette
from dfr.ui.viewmodels.shell import ShellViewModel, TierMix

ORG, APP = "EXDesigner", "DfR Toolkit"


class MainWindow(QMainWindow):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        self.palette_: Palette = PALETTES[vm.palette_name.value]
        self.setWindowTitle(f"DfR Toolkit {__version__}")
        self.resize(1400, 860)
        self.setDockNestingEnabled(True)
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self.tabs)
        self._open: dict[str, QWidget] = {}

        self.screens: dict[str, ScreenEntry] = {
            e.spec.id: e for e in discover_screens(vm.present_modules)
        }
        self.project = ProjectPanel(vm, self.palette_, self.open_screen)
        self.project.set_screens(
            [(e.spec.id, e.spec.title, e.spec.step) for e in self.screens.values()]
        )
        self.properties = PropertiesPanel(vm)
        self.messages = MessagesPanel(vm, self.palette_)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.messages)
        self._default_dock_sizes()

        self._build_menus()
        self._build_status()
        self.apply_theme()
        self._restore_layout()
        vm.palette_name.changed.connect(lambda _: self.apply_theme())
        vm.status_text.changed.connect(self.status_design.setText)
        vm.tier_mix.changed.connect(self._show_tier_mix)
        vm.current_run_id.changed.connect(
            lambda rid: self.status_run.setText(f"run #{rid}" if rid else "no run")
        )
        vm.active_step.changed.connect(lambda _: self.project.rebuild())
        vm.navigate.connect(self.open_screen)
        if "home" in self.screens:
            self.open_screen("home")

    # ----------------------------------------------------------------- chrome
    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        view_menu = self.menuBar().addMenu("&View")
        help_menu = self.menuBar().addMenu("&Help")
        for label, sid, key in (
            ("&Designs…", "home", QKeySequence.StandardKey.Open),
            ("&Import BOM + netlist…", "import_design", QKeySequence.StandardKey.New),
            ("&Report…", "report", QKeySequence.StandardKey.Print),
        ):
            if sid in self.screens:
                act = QAction(label, self)
                act.setShortcut(key)
                act.triggered.connect(lambda _=False, s=sid: self.open_screen(s))
                file_menu.addAction(act)
        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        for dock in (self.project, self.properties, self.messages):
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        theme = QAction("Toggle light / dark theme", self)
        theme.triggered.connect(self.vm.toggle_palette)
        view_menu.addAction(theme)
        reset = QAction("Reset panel layout", self)
        reset.triggered.connect(self._reset_layout)
        view_menu.addAction(reset)
        about = QAction("About", self)
        about.triggered.connect(self.show_about)
        help_menu.addAction(about)

        bar = QToolBar("Main")
        bar.setObjectName("toolbar_main")
        bar.setMovable(False)
        self.addToolBar(bar)
        for sid in (
            "home",
            "import_design",
            "circuit",
            "conditions",
            "results",
            "refine",
            "report",
        ):
            if sid in self.screens:
                act = QAction(self.screens[sid].spec.title, self)
                act.triggered.connect(lambda _=False, s=sid: self.open_screen(s))
                bar.addAction(act)
        bar.addSeparator()
        bar.addAction(theme)

    def about_text(self) -> str:
        modules = ", ".join(sorted(self.vm.present_modules))
        return (
            f"<b>DfR Toolkit {__version__}</b><br>Design for Reliability analysis for power "
            f"converters, offline.<br><br><b>Modules:</b> {modules}<br>"
            f"<b>Screens:</b> {', '.join(e.spec.title for e in self.screens.values())}"
        )

    def show_about(self) -> None:
        QMessageBox.about(self, "About DfR Toolkit", self.about_text())

    def _build_status(self) -> None:
        self.status_design = QLabel(self.vm.status_text.value)
        self.status_run = QLabel("no run")
        self.status_tier = QLabel("")
        for w in (self.status_design, self.status_run):
            self.statusBar().addWidget(w)
        self.statusBar().addPermanentWidget(self.status_tier)
        self._show_tier_mix(self.vm.tier_mix.value)

    def _show_tier_mix(self, mix: TierMix) -> None:
        self.status_tier.setText(f"Tier mix: {mix.label}")

    def apply_theme(self) -> None:
        self.palette_ = PALETTES[self.vm.palette_name.value]
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(build_qss(self.palette_))
        self.project.palette_ = self.palette_
        self.messages.palette_ = self.palette_
        self.project.rebuild()
        self.messages.show_messages(self.vm.messages)

    # ----------------------------------------------------------------- documents
    def open_screen(self, screen_id: str) -> None:
        entry = self.screens.get(screen_id)
        if entry is None:
            return
        widget = self._open.get(screen_id)
        if widget is None:
            widget = entry.build(self.vm)
            widget.setObjectName(f"screen_{screen_id}")
            self._open[screen_id] = widget
            self.tabs.addTab(widget, entry.spec.title)
        self.tabs.setCurrentWidget(widget)
        self.vm.active_step.set(entry.spec.step)

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        for sid, w in list(self._open.items()):
            if w is widget:
                del self._open[sid]
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

    # ----------------------------------------------------------------- layout persistence
    def _settings(self) -> QSettings:
        return QSettings(ORG, APP)

    def _restore_layout(self) -> None:
        s = self._settings()
        geo = s.value("geometry")
        state = s.value("windowState")
        if isinstance(geo, QByteArray):
            self.restoreGeometry(geo)
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def _reset_layout(self) -> None:
        for dock, area in (
            (self.project, Qt.DockWidgetArea.LeftDockWidgetArea),
            (self.properties, Qt.DockWidgetArea.RightDockWidgetArea),
            (self.messages, Qt.DockWidgetArea.BottomDockWidgetArea),
        ):
            dock.setFloating(False)
            dock.show()
            self.addDockWidget(area, dock)
        self._default_dock_sizes()

    def _default_dock_sizes(self) -> None:
        """First-run / reset widths: stepper and Properties readable, Messages a strip."""
        self.resizeDocks([self.project, self.properties], [220, 320], Qt.Orientation.Horizontal)
        self.resizeDocks([self.messages], [160], Qt.Orientation.Vertical)

    def closeEvent(self, event: QCloseEvent) -> None:  # Qt override
        s = self._settings()
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())
        self.vm.commit()
        super().closeEvent(event)
