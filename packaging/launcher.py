"""Frozen-app entry point. Routes data-file lookups to the PyInstaller bundle and opens the GUI
with a per-user design database under %APPDATA%\\DfR (PRD A1: no admin rights needed)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def main() -> int:
    os.environ.setdefault("DFR_DATA_DIR", str(_bundle_root() / "data"))
    appdata = Path(os.environ.get("APPDATA", Path.home())) / "DfR"
    appdata.mkdir(parents=True, exist_ok=True)
    (appdata / "plugins").mkdir(exist_ok=True)
    db = appdata / "designs.dfr"
    argv = sys.argv[1:]
    if argv and argv[0] != "gui":
        from dfr.__main__ import main as cli_main

        return cli_main(argv)
    from dfr.ui.shell.app import run_gui

    return run_gui(db)


if __name__ == "__main__":
    raise SystemExit(main())
