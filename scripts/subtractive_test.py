"""MOD-03: run the test suite with each optional module/topology folder deleted in turn.

The source tree is copied to a temporary directory inside the repo (``.subtractive/``),
one folder is removed per iteration, and pytest runs against the copy. Nothing outside
the repository is touched.

Usage: python scripts/subtractive_test.py [--only <folder-name>]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATE_ROOTS = (REPO / "dfr" / "modules", REPO / "dfr" / "topologies")
COPY_ITEMS = ("dfr", "tests", "data", "pyproject.toml")
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".mypy_cache", ".hypothesis")


def candidates() -> list[Path]:
    found: list[Path] = []
    for root in CANDIDATE_ROOTS:
        if not root.is_dir():
            continue
        found.extend(p for p in sorted(root.iterdir()) if p.is_dir() and (p / "module.py").exists())
    return found


def run_without(folder: Path, workdir: Path) -> int:
    for item in COPY_ITEMS:
        src = REPO / item
        if src.is_dir():
            shutil.copytree(src, workdir / item, ignore=IGNORE)
        elif src.is_file():
            shutil.copy2(src, workdir / item)
    shutil.rmtree(workdir / folder.relative_to(REPO))
    print(f"\n=== pytest without {folder.relative_to(REPO)} ===", flush=True)
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=workdir,
        env={**__import__("os").environ, "PYTHONPATH": str(workdir)},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="only delete the folder with this name")
    args = parser.parse_args()

    targets = [c for c in candidates() if args.only is None or c.name == args.only]
    if not targets:
        print("no module folders found; nothing to do")
        return 0

    scratch_root = REPO / ".subtractive"
    scratch_root.mkdir(exist_ok=True)
    failures: list[str] = []
    for folder in targets:
        with tempfile.TemporaryDirectory(dir=scratch_root) as tmp:
            if run_without(folder, Path(tmp)) != 0:
                failures.append(folder.name)
    shutil.rmtree(scratch_root, ignore_errors=True)

    if failures:
        print(f"\nFAILED without: {', '.join(failures)}")
        return 1
    print(f"\nOK: suite passes with each of {[t.name for t in targets]} removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
