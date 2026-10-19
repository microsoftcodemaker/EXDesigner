# PyInstaller spec: one-folder build (PRD 2.4: one-folder avoids slow one-file startup).
# Build with:  python -m PyInstaller packaging/dfr.spec --noconfirm
# Output:      dist/DfRToolkit/DfRToolkit.exe
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH is injected by PyInstaller
sys.path.insert(0, str(ROOT))

# Modules, topologies and screens are discovered by folder scan at runtime, so PyInstaller
# cannot see them statically: collect every submodule of the plugin packages.
hidden = (
    collect_submodules("dfr.modules")
    + collect_submodules("dfr.topologies")
    + collect_submodules("dfr.ui.screens")
    + collect_submodules("dfr.core.db.migrations")
    + ["pint.delegates.formatter.full", "sqlalchemy.dialects.sqlite"]
)

datas = (
    [(str(ROOT / "data"), "data")]
    + [(str(ROOT / "dfr" / "modules" / "m1_bom" / "data"), "dfr/modules/m1_bom/data")]
    + [(str(ROOT / "dfr" / "modules" / "m11_report" / "templates"), "dfr/modules/m11_report/templates")]
    + [(str(ROOT / "dfr" / "core" / "db" / "migrations"), "dfr/core/db/migrations")]
    + [(str(p), str(p.relative_to(ROOT).parent)) for p in (ROOT / "dfr" / "modules").glob("*/migrations/*.py")]
    + collect_data_files("pint")
)

# Qt modules the app does not use; dropping them keeps the folder well under the PRD's 400 MB target.
excludes = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DRender", "PySide6.QtBluetooth", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtLocation", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtQuick",
    "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.QtQml", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio", "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtSvgWidgets",
    "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    "PySide6.QtHttpServer", "PySide6.QtPdfWidgets", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtHelp", "PySide6.QtAxContainer",
    "tkinter", "matplotlib.tests", "numpy.tests", "pandas.tests", "hypothesis", "pytest", "mypy", "ruff",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DfRToolkit",
    debug=False,
    console=False,
    icon=None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DfRToolkit",
)
