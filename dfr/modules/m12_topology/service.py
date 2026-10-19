"""M12: topology pattern match, role and rail proposal, user confirmation (PRD 3.12).

Patterns come from topology plugins through the registry service ``topology.patterns``
(each returns ``{pattern_id: TopologyPattern}``); M12 never imports a topology folder.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from dfr.core.contracts import (
    Diagnostic,
    NetlistGraph,
    Part,
    PatternMatch,
    RoleAssignment,
    RoleEdit,
    RoleMap,
    RoleProposal,
    Stage,
    StageStatus,
)
from dfr.core.db.repos import StageRepo
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.extension import TopologyPattern
from dfr.core.ports import Clock

MODULE_ID = "m12_topology"
LOW_CONFIDENCE = 0.7  # proposals below this are highlighted (PRD 3.12)

PatternSource = Callable[[], Mapping[str, TopologyPattern]]
InferenceFn = Callable[[PatternMatch, NetlistGraph, list[Part]], dict[str, dict[str, str]]]


@dataclass
class MatchOutcome:
    pattern_id: str
    matches: list[PatternMatch]
    proposal: RoleProposal | None
    inferred_pins: dict[str, dict[str, str]] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.proposal is not None


def available_patterns(sources: list[PatternSource]) -> dict[str, TopologyPattern]:
    patterns: dict[str, TopologyPattern] = {}
    for src in sources:
        patterns.update(src())
    return patterns


def match_topology(
    graph: NetlistGraph,
    parts: list[Part],
    pattern_id: str,
    patterns: Mapping[str, TopologyPattern],
    *,
    inference: Mapping[str, InferenceFn] | None = None,
    chosen_index: int = 0,
    bom_hints: Mapping[str, tuple[str, ...]] | None = None,
) -> MatchOutcome:
    """Run the user-selected pattern (REC-01), propose roles for the chosen candidate (REC-08)."""
    sink = DiagnosticSink(MODULE_ID)
    pattern = patterns.get(pattern_id)
    if pattern is None:
        sink.error("TOPO_UNKNOWN_PATTERN", f"no topology pattern {pattern_id!r} is installed")
        return MatchOutcome(pattern_id, [], None, diagnostics=list(sink.items))

    matches = pattern.match(graph, parts)
    if not matches:
        sink.error(
            "TOPO_NO_MATCH",
            f"{pattern_id}: no candidate stage; check for an inductor on a switch node, "
            "or assign roles manually",
        )
        return MatchOutcome(pattern_id, [], None, diagnostics=list(sink.items))

    if len(matches) > 1:
        sink.info(
            "TOPO_MULTIPLE_CANDIDATES",
            f"{len(matches)} candidate stages; using #{chosen_index + 1} "
            f"(sw={matches[min(chosen_index, len(matches) - 1)].rails.get('sw')})",
        )
    chosen = matches[min(chosen_index, len(matches) - 1)]
    for unmet in chosen.unmet:
        sink.warning("TOPO_UNMET_CONSTRAINT", f"{pattern_id}: {unmet} not satisfied")
    if chosen.confidence < LOW_CONFIDENCE:
        sink.warning(
            "TOPO_LOW_CONFIDENCE",
            f"{pattern_id}: confidence {chosen.confidence:.2f} < {LOW_CONFIDENCE}; "
            "review every role",
        )
    _hint_conflicts(chosen, parts, bom_hints or {}, pattern_id, sink)

    proposal = pattern.propose(chosen, parts)
    inferred = (
        inference[pattern_id](chosen, graph, parts) if inference and pattern_id in inference else {}
    )
    return MatchOutcome(pattern_id, matches, proposal, inferred, list(sink.items))


def apply_edits(proposal: RoleProposal, edits: list[RoleEdit]) -> RoleProposal:
    """User edits on the Circuit Review screen; edited rows get provenance ``user``."""
    from dfr.core.contracts import ProposalProvenance  # noqa: PLC0415

    by_ref = {a.refdes: a for a in proposal.assignments}
    for e in edits:
        prev = by_ref.get(e.refdes)
        by_ref[e.refdes] = RoleAssignment(
            refdes=e.refdes,
            role=e.role,
            rail=e.rail,
            confidence=1.0,
            evidence=f"user edit (was {prev.role if prev else 'unassigned'})",
            provenance=ProposalProvenance.USER,
        )
    return proposal.model_copy(update={"assignments": list(by_ref.values())})


def confirm_roles(
    session: Session,
    clock: Clock,
    *,
    design_version_id: int,
    proposal: RoleProposal,
    edits: list[RoleEdit],
    netlist_hash: str | None,
) -> Stage:
    """Persist the proposal (with edits) and mark it confirmed (REC-06, REC-07)."""
    final = apply_edits(proposal, edits)
    repo = StageRepo(session, clock)
    stage = repo.add(
        design_version_id,
        Stage(
            pattern_id=final.pattern_id,
            pattern_version=final.pattern_version,
            match_confidence=final.confidence,
            netlist_hash=netlist_hash,
            status=StageStatus.PROPOSED,
            rails=final.rails,
            assignments=final.assignments,
        ),
    )
    assert stage.id is not None
    repo.confirm(stage.id)
    confirmed = repo.get(stage.id)
    assert confirmed is not None
    return confirmed


def role_map_for(session: Session, clock: Clock, stage_id: int) -> RoleMap:
    return StageRepo(session, clock).role_map(stage_id)


def check_staleness(
    session: Session, clock: Clock, stage: Stage, current_netlist_hash: str | None
) -> bool:
    """Mark the stage stale when the netlist changed; returns True if stale (REC-07, NET-09)."""
    if stage.id is None or stage.netlist_hash == current_netlist_hash:
        return False
    StageRepo(session, clock).mark_stale(stage.id)
    return True


def prefill_from_stale(stale: Stage, proposal: RoleProposal) -> RoleProposal:
    """Carry user-confirmed roles over to a new proposal by refdes (PRD 3.12 staleness)."""
    from dfr.core.contracts import ProposalProvenance  # noqa: PLC0415

    confirmed = {a.refdes: a for a in stale.assignments if a.provenance is ProposalProvenance.USER}
    merged = [
        confirmed[a.refdes].model_copy(
            update={"evidence": f"carried from stale stage; {a.evidence}"}
        )
        if a.refdes in confirmed
        else a
        for a in proposal.assignments
    ]
    return proposal.model_copy(update={"assignments": merged})


def _hint_conflicts(
    match: PatternMatch,
    parts: list[Part],
    hints: Mapping[str, tuple[str, ...]],
    pattern_id: str,
    sink: DiagnosticSink,
) -> None:
    """BOM text hints are evidence layer 4: raise or lower confidence, never decisive."""
    family = "buck"
    contradicting = {"boost", "step-up", "ldo", "flyback"}
    for refdes in match.roles.get("ic", ()):
        part = next((p for p in parts if p.refdes == refdes), None)
        keys = [refdes, part.mpn if part and part.mpn else ""]
        words = {h for k in keys for h in hints.get(k, ())}
        if words & contradicting:
            sink.warning(
                "TOPO_HINT_CONFLICT",
                f"{refdes}: BOM text says {sorted(words & contradicting)} but pattern is {family}",
            )
        elif words & {"buck", "step-down"}:
            sink.info("TOPO_HINT_AGREES", f"{refdes}: BOM text mentions {sorted(words)}")
    del pattern_id
