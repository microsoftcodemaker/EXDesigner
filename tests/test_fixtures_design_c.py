"""Baseline facts about the Design C fixtures (plain text scan; parsers arrive in T05/T09)."""

from __future__ import annotations

import re

from tests.conftest import FIXTURES

NETLIST = FIXTURES / "design_c" / "design_c_protel.net"
BOMDOC = FIXTURES / "design_c" / "design_c.BomDoc"


def test_protel_netlist_shape() -> None:
    raw = NETLIST.read_bytes()
    assert b"\r\n" in raw, "fixture must keep CRLF line endings"
    text = raw.decode("ascii")
    lines = text.split("\r\n")
    assert lines.count("[") == lines.count("]") == 28
    assert lines.count("(") == lines.count(")") == 19
    # empty net SCL: "(" / "SCL" / ")"
    i = lines.index("SCL")
    assert lines[i - 1] == "(" and lines[i + 1] == ")"
    # sw net of the integrated buck
    j = lines.index("NetC3_1")
    assert lines[j + 1 : j + 4] == ["C3-1", "L1-1", "U3-7"]
    mpns = [lines[k + 3] for k, ln in enumerate(lines) if ln == "["]
    assert "Copy of MHDR1X3" in mpns  # MPN with spaces
    assert "LM63635CC3QDRRRQ1" in mpns


def test_bomdoc_shape() -> None:
    raw = BOMDOC.read_bytes()
    text = raw.decode("latin-1")
    items = [ln for ln in text.split("\r\n") if ln.startswith("|RECORD=CatalogItem|")]
    assert len(items) == 22
    mpns = {re.search(r"\|USERCOMMENTS=([^|]*)", ln).group(1) for ln in items}
    assert len(mpns) == 22
    net_lines = NETLIST.read_bytes().decode("ascii").split("\r\n")
    netlist_mpns = {net_lines[k + 3] for k, ln in enumerate(net_lines) if ln == "["}
    assert netlist_mpns == mpns, "NET-10: join by MPN with 0 unmatched"
    assert "DESCRIPTION=FIXED IND 10UH 4.2A 86.35MOHM SM" in text
