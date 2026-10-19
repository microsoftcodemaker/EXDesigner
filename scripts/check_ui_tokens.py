"""MOD-08: ban hard-coded colors in ``dfr/ui`` outside the design-token file.

Fails if any ``#rrggbb``/``#rgb`` literal, ``rgb(``/``rgba(`` call, or ``QColor("...")`` with a
literal appears in a UI source file other than ``dfr/ui/tokens.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UI_DIR = REPO / "dfr" / "ui"
TOKENS_FILE = UI_DIR / "tokens.py"

PATTERNS = (
    re.compile(r"""["']#[0-9a-fA-F]{3,8}["']"""),
    re.compile(r"\brgba?\("),
    re.compile(r"""QColor\(\s*["']"""),
)


def main() -> int:
    bad: list[str] = []
    for path in UI_DIR.rglob("*.py"):
        if path == TOKENS_FILE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(p.search(line) for p in PATTERNS):
                bad.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()}")
    if bad:
        print("Hard-coded colors found (use dfr/ui/tokens.py):")
        print("\n".join(bad))
        return 1
    print("OK: no hard-coded colors outside tokens.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
