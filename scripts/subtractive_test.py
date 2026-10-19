"""MOD-03: run the test suite with each *optional* module/topology folder deleted in turn.

For every folder under dfr/modules and dfr/topologies whose ``module.py`` declares
``MODULE.optional = True``, the source tree is copied to a scratch directory inside the repo
(``.subtractive/``), that folder and its own tests (``tests/<folder>/`` and ``tests/<id>/``)
are removed, and pytest runs against the copy. Required modules (``optional=False``) are
skipped: the app is allowed to depend on them. Nothing outside the repository is touched.

Usage: python scripts/subtractive_test.py [--only <folder-name>] [--include-required]
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CANDIDATE_ROOTS = (REPO / "dfr" / "modules", REPO / "dfr" / "topologies")
COPY_ITEMS = ("dfr", "tests", "data", "pyproject.toml")
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".mypy_cache", ".hypothesis")


@dataclass(frozen=True)
class Candidate:
    folder: Path
    module_id: str
    optional: bool

    @property
    def test_dirs(self) -> tuple[Path, ...]:
        names = {self.folder.name, self.module_id}
        return tuple(REPO / "tests" / n for n in sorted(names))


def candidates() -> list[Candidate]:
    found: list[Candidate] = []
    for root in CANDIDATE_ROOTS:
        if not root.is_dir():
            continue
        for folder in sorted(
            p for p in root.iterdir() if p.is_dir() and (p / "module.py").exists()
        ):
            dotted = f"dfr.{root.name}.{folder.name}.module"
            try:
                spec = importlib.import_module(dotted).MODULE
            except Exception as exc:  # noqa: BLE001 - report and skip, like the registry does
                print(f"skip {folder.relative_to(REPO)}: cannot import ({exc!r})")
                continue
            found.append(Candidate(folder, spec.id, bool(spec.optional)))
    return found


def run_without(cand: Candidate, workdir: Path) -> int:
    for item in COPY_ITEMS:
        src = REPO / item
        if src.is_dir():
            shutil.copytree(src, workdir / item, ignore=IGNORE)
        elif src.is_file():
            shutil.copy2(src, workdir / item)
    shutil.rmtree(workdir / cand.folder.relative_to(REPO))
    removed_tests = []
    for tdir in cand.test_dirs:
        target = workdir / tdir.relative_to(REPO)
        if target.is_dir():
            shutil.rmtree(target)
            removed_tests.append(tdir.relative_to(REPO).as_posix())
    extra = f" (and {', '.join(removed_tests)})" if removed_tests else ""
    print(f"\n=== pytest without {cand.folder.relative_to(REPO)}{extra} ===", flush=True)
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=workdir,
        env={**os.environ, "PYTHONPATH": str(workdir)},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="only delete the folder with this name")
    parser.add_argument(
        "--include-required", action="store_true", help="also subtract optional=False modules"
    )
    args = parser.parse_args()

    targets = [
        c
        for c in candidates()
        if (args.only is None or c.folder.name == args.only)
        and (c.optional or args.include_required)
    ]
    skipped = [c for c in candidates() if not c.optional and not args.include_required]
    for c in skipped:
        print(f"skip {c.folder.relative_to(REPO)}: required module (optional=False)")
    if not targets:
        print("no optional module folders found; nothing to do")
        return 0

    scratch_root = REPO / ".subtractive"
    scratch_root.mkdir(exist_ok=True)
    failures: list[str] = []
    for cand in targets:
        with tempfile.TemporaryDirectory(dir=scratch_root) as tmp:
            if run_without(cand, Path(tmp)) != 0:
                failures.append(cand.folder.name)
    shutil.rmtree(scratch_root, ignore_errors=True)

    if failures:
        print(f"\nFAILED without: {', '.join(failures)}")
        return 1
    print(f"\nOK: suite passes with each of {[t.folder.name for t in targets]} removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
