"""M12 service behaviour with a stub pattern (independent of any topology folder)."""

from __future__ import annotations

from collections.abc import Sequence

from dfr.core.contracts import (
    NetlistGraph,
    Part,
    PartClass,
    PatternMatch,
    ProposalProvenance,
    Rail,
    RoleAssignment,
    RoleEdit,
    RoleProposal,
)
from dfr.core.extension import TopologyPattern
from dfr.modules.m12_topology.service import apply_edits, available_patterns, match_topology


class StubPattern(TopologyPattern):
    id = "stub"
    version = "0.0.1"
    roles = ("thing", "other")
    rails = ("a",)

    def __init__(self, matches: list[PatternMatch]) -> None:
        self._matches = matches

    def match(self, graph: NetlistGraph, parts: Sequence[Part]) -> list[PatternMatch]:
        return list(self._matches)

    def propose(self, match: PatternMatch, parts: Sequence[Part]) -> RoleProposal:
        return RoleProposal(
            pattern_id=self.id,
            pattern_version=self.version,
            confidence=match.confidence,
            rails=[Rail(rail=r, net_name=n) for r, n in match.rails.items()],
            assignments=[RoleAssignment(refdes="X1", role="thing", rail="a")],
        )


def _match(conf: float, unmet: list[str] | None = None) -> PatternMatch:
    return PatternMatch(
        pattern_id="stub",
        pattern_version="0.0.1",
        confidence=conf,
        rails={"a": "N1"},
        roles={"thing": ("X1",)},
        unmet=unmet or [],
    )


PARTS = [Part(refdes="X1", part_class=PartClass.IC)]


def test_available_patterns_merges_sources() -> None:
    p1, p2 = StubPattern([]), StubPattern([])
    p2.id = "stub2"
    merged = available_patterns([lambda: {"stub": p1}, lambda: {"stub2": p2}])
    assert set(merged) == {"stub", "stub2"}


def test_unknown_pattern_and_no_match_are_diagnostics() -> None:
    out = match_topology(NetlistGraph(), PARTS, "nope", {"stub": StubPattern([])})
    assert not out.matched and out.diagnostics[0].code == "TOPO_UNKNOWN_PATTERN"
    out = match_topology(NetlistGraph(), PARTS, "stub", {"stub": StubPattern([])})
    assert not out.matched and out.diagnostics[0].code == "TOPO_NO_MATCH"


def test_low_confidence_unmet_and_candidate_choice() -> None:
    pat = StubPattern([_match(0.9), _match(0.4, ["x"])])
    out = match_topology(NetlistGraph(), PARTS, "stub", {"stub": pat}, chosen_index=1)
    codes = {d.code for d in out.diagnostics}
    assert {"TOPO_MULTIPLE_CANDIDATES", "TOPO_UNMET_CONSTRAINT", "TOPO_LOW_CONFIDENCE"} <= codes
    assert out.matched and out.proposal.confidence == 0.4
    out2 = match_topology(NetlistGraph(), PARTS, "stub", {"stub": pat}, chosen_index=99)
    assert out2.proposal.confidence == 0.4  # clamped to last candidate


def test_apply_edits_marks_user_provenance() -> None:
    proposal = StubPattern([]).propose(_match(0.9), PARTS)
    edited = apply_edits(
        proposal, [RoleEdit(refdes="X1", role="other"), RoleEdit(refdes="Y9", role="thing")]
    )
    by = {a.refdes: a for a in edited.assignments}
    assert by["X1"].role == "other" and by["X1"].provenance is ProposalProvenance.USER
    assert "was thing" in by["X1"].evidence
    assert by["Y9"].role == "thing" and "unassigned" in by["Y9"].evidence
