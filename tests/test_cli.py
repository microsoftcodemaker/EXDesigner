from __future__ import annotations

import pytest

from dfr.__main__ import main


def test_status_runs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "DfR Toolkit" in out and "Pipeline order" in out


def test_demo_runs_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "run #1 completed" in out
    assert "ind_isat" in out and "WARN" in out  # 3.84 A peak on a 4.2 A Isat part at 0.8 derating
