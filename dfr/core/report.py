"""HTML helpers shared by every report section (PRD 3.11, RPT-02).

Any module may contribute a report section; it renders numbers through ``num()`` so each one
carries a tier badge and a source tag, and lays rows out with ``table()``. Kept in core so that
modules never import the reporting module.
"""

from __future__ import annotations

from html import escape

SOURCE_LABELS = {"equation": "eq", "manual": "man", "measured": "meas", "simulated": "sim"}


def num(value: float | None, tier: int, source: str, fmt: str = "{:.4g}") -> str:
    """A displayed number: value (or an em dash), tier badge and source label."""
    text = fmt.format(value) if value is not None else "—"
    return (
        f'<span class="value">{text}</span><span class="badge t{tier}">T{tier}</span>'
        f'<span class="src">{SOURCE_LABELS.get(source, source)}</span>'
    )


def table(headers: list[str], rows: list[list[str]], classes: list[str] | None = None) -> str:
    """A plain table; cells are HTML (escape text yourself), headers are escaped here."""
    classes = classes or [""] * len(headers)
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>"
        + "".join(f'<td class="{classes[i]}">{cell}</td>' for i, cell in enumerate(r))
        + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def muted(text: str) -> str:
    return f"<p class='muted'>{escape(text)}</p>"


__all__ = ["SOURCE_LABELS", "muted", "num", "table"]
