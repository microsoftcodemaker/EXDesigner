"""Structured warnings. Modules never raise on bad part data; they emit one of these and skip."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from dfr.core.contracts.v1.enums import Severity


class Diagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    severity: Severity
    message: str
    module: str | None = None
    part_id: int | None = None
    line_no: int | None = None

    def __str__(self) -> str:
        where = f" (line {self.line_no})" if self.line_no is not None else ""
        who = f"[{self.module}] " if self.module else ""
        return f"{who}{self.severity.value.upper()} {self.code}{where}: {self.message}"
