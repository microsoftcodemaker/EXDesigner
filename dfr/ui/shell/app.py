"""GUI entry point: ``python -m dfr.ui`` or ``python -m dfr gui [--db file.dfr]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from dfr.ui.shell.main_window import MainWindow
from dfr.ui.viewmodels.shell import ShellViewModel


def run_gui(db_path: Path | None = None, argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv or sys.argv[:1])
    app.setApplicationName("DfR Toolkit")
    app.setOrganizationName("EXDesigner")
    vm = ShellViewModel(db_path=db_path)
    window = MainWindow(vm)
    window.show()
    try:
        return int(app.exec())
    finally:
        vm.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dfr gui")
    parser.add_argument(
        "--db", type=Path, default=None, help="design database (.dfr); default in-memory"
    )
    args = parser.parse_args(argv)
    return run_gui(args.db)


if __name__ == "__main__":
    raise SystemExit(main())
