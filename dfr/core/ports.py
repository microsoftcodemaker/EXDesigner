"""Ports for side effects (clock, filesystem, network). Inject real or fake implementations.

Modules must not call ``datetime.now()``, ``open()`` or any HTTP library directly;
they take one of these protocols as an argument so tests stay deterministic and the
offline guarantee (PRD NFR-07) can be enforced by injecting :class:`NoNetwork`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class FileSystem(Protocol):
    def read_bytes(self, path: Path) -> bytes: ...
    def write_bytes(self, path: Path, data: bytes) -> None: ...
    def exists(self, path: Path) -> bool: ...


@runtime_checkable
class Network(Protocol):
    def enabled(self) -> bool: ...
    def get(self, url: str, timeout_s: float = 10.0) -> bytes: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, **delta: float) -> None:
        self._at = self._at + timedelta(**delta)


class LocalFileSystem:
    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def exists(self, path: Path) -> bool:
        return path.exists()


class MemoryFileSystem:
    def __init__(self, files: dict[Path, bytes] | None = None) -> None:
        self.files: dict[Path, bytes] = dict(files or {})

    def read_bytes(self, path: Path) -> bytes:
        return self.files[path]

    def write_bytes(self, path: Path, data: bytes) -> None:
        self.files[path] = data

    def exists(self, path: Path) -> bool:
        return path in self.files


class NoNetwork:
    """Default: the app never touches the network (PRD NFR-07)."""

    def enabled(self) -> bool:
        return False

    def get(self, url: str, timeout_s: float = 10.0) -> bytes:
        msg = f"Network access is disabled (requested {url})"
        raise PermissionError(msg)
