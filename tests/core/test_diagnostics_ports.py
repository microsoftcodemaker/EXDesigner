from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dfr.core.contracts import Severity
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.ports import (
    Clock,
    FileSystem,
    FixedClock,
    LocalFileSystem,
    MemoryFileSystem,
    Network,
    NoNetwork,
    SystemClock,
)


def test_sink_collects_without_raising() -> None:
    sink = DiagnosticSink("m1")
    sink.info("A", "a")
    sink.warning("B", "b", part_id=3)
    sink.error("C", "c", line_no=7)
    assert len(sink) == 3
    assert sink.has_errors
    assert [d.module for d in sink] == ["m1"] * 3
    assert sink.items[1].part_id == 3
    assert sink.items[2].line_no == 7


def test_sink_extend_and_no_errors() -> None:
    a = DiagnosticSink("x")
    a.info("I", "i")
    b = DiagnosticSink("y")
    b.extend(a)
    assert not b.has_errors
    assert b.items[0].severity is Severity.INFO


def test_ports_protocols() -> None:
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FixedClock(datetime.now(UTC)), Clock)
    assert isinstance(LocalFileSystem(), FileSystem)
    assert isinstance(MemoryFileSystem(), FileSystem)
    assert isinstance(NoNetwork(), Network)


def test_fixed_clock_advance() -> None:
    c = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    c.advance(hours=2)
    assert c.now() == datetime(2026, 1, 1, 2, tzinfo=UTC)


def test_memory_fs_roundtrip() -> None:
    fs = MemoryFileSystem()
    p = Path("a/b.txt")
    assert not fs.exists(p)
    fs.write_bytes(p, b"hi")
    assert fs.exists(p)
    assert fs.read_bytes(p) == b"hi"


def test_local_fs(tmp_path: Path) -> None:
    fs = LocalFileSystem()
    p = tmp_path / "sub" / "f.bin"
    fs.write_bytes(p, b"\x00\x01")
    assert fs.exists(p)
    assert fs.read_bytes(p) == b"\x00\x01"


def test_no_network_refuses() -> None:
    n = NoNetwork()
    assert not n.enabled()
    with pytest.raises(PermissionError):
        n.get("https://example.invalid")
