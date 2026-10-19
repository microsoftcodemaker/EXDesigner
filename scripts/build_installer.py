"""T25: build the one-folder app with PyInstaller and (if Inno Setup is installed) the installer.

Usage: python scripts/build_installer.py [--skip-inno] [--clean]
Needs: pip install pyinstaller   (dev machine only; not a project dependency)
Writes: dist/DfRToolkit/ and dist/DfRToolkit-Setup-<ver>.exe. Both are git-ignored.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "packaging" / "dfr.spec"
ISS = REPO / "packaging" / "installer.iss"
DIST = REPO / "dist" / "DfRToolkit"


def folder_size_mb(path: Path) -> float:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1e6


def prune_qt(qt: Path) -> float:
    """Drop Qt translations and non-English WebEngine locales (PRD R7 size risk). Returns MB freed."""
    freed = 0.0
    translations = qt / "translations"
    if translations.is_dir():
        for p in translations.rglob("*"):
            if not p.is_file():
                continue
            in_locales = p.parent.name == "qtwebengine_locales"
            keep = in_locales and p.stem in ("en-US", "en-GB")
            if not keep:
                freed += p.stat().st_size / 1e6
                p.unlink()
    return freed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-inno", action="store_true")
    parser.add_argument("--clean", action="store_true", help="remove build/ and dist/ first")
    args = parser.parse_args()
    if args.clean:
        for d in (REPO / "build", REPO / "dist"):
            shutil.rmtree(d, ignore_errors=True)

    rc = subprocess.call(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean"], cwd=REPO
    )
    if rc != 0:
        print("PyInstaller failed")
        return rc
    pruned = prune_qt(DIST / "_internal" / "PySide6")
    size = folder_size_mb(DIST)
    print(
        f"one-folder build: {DIST} ({size:.0f} MB after pruning {pruned:.0f} MB; "
        "PRD target < 400 MB installer, LZMA roughly halves this)"
    )

    smoke = subprocess.run(
        [str(DIST / "DfRToolkit.exe"), "status"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(smoke.stdout[-800:])
    if smoke.returncode != 0:
        print("frozen app smoke test failed:", smoke.stderr[-800:])
        return smoke.returncode

    if args.skip_inno:
        return 0
    iscc = shutil.which("iscc") or shutil.which("ISCC")
    if iscc is None:
        for candidate in (
            Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
            Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        ):
            if candidate.exists():
                iscc = str(candidate)
    if iscc is None:
        print(
            "Inno Setup (ISCC.exe) not found; skipped installer. Install from jrsoftware.org or use --skip-inno."
        )
        return 0
    return subprocess.call([iscc, str(ISS)], cwd=REPO)


if __name__ == "__main__":
    raise SystemExit(main())
