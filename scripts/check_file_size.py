"""PRD rule 7 (file size guideline, under 400 lines). Warning only; never fails CI."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIMIT = 400
SKIP_PARTS = ("migrations",)


def main() -> int:
    over: list[tuple[int, Path]] = []
    for path in (REPO / "dfr").rglob("*.py"):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        n = sum(1 for _ in path.open(encoding="utf-8"))
        if n > LIMIT:
            over.append((n, path.relative_to(REPO)))
    for n, p in sorted(over, reverse=True):
        print(f"WARN {p} has {n} lines (> {LIMIT}); consider splitting")
    if not over:
        print(f"OK: all source files under {LIMIT} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
