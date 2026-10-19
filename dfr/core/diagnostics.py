"""Diagnostic collection helpers. Modules append; the orchestrator persists."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.contracts.v1.enums import Severity


class DiagnosticSink:
    """Accumulates diagnostics for one module invocation. Never raises."""

    def __init__(self, module: str | None = None) -> None:
        self.module = module
        self._items: list[Diagnostic] = []

    def add(
        self,
        code: str,
        message: str,
        severity: Severity = Severity.WARNING,
        *,
        part_id: int | None = None,
        line_no: int | None = None,
    ) -> Diagnostic:
        diag = Diagnostic(
            code=code,
            severity=severity,
            message=message,
            module=self.module,
            part_id=part_id,
            line_no=line_no,
        )
        self._items.append(diag)
        return diag

    def info(self, code: str, message: str, **kw: int | None) -> Diagnostic:
        return self.add(code, message, Severity.INFO, **kw)

    def warning(self, code: str, message: str, **kw: int | None) -> Diagnostic:
        return self.add(code, message, Severity.WARNING, **kw)

    def error(self, code: str, message: str, **kw: int | None) -> Diagnostic:
        return self.add(code, message, Severity.ERROR, **kw)

    def extend(self, items: Iterable[Diagnostic]) -> None:
        self._items.extend(items)

    @property
    def items(self) -> tuple[Diagnostic, ...]:
        return tuple(self._items)

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self._items)

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        """An empty sink is still a sink; never let ``sink or default`` discard it."""
        return True
