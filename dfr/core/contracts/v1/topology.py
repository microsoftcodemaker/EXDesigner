"""Topology match, roles and rails (PRD section 3.12)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dfr.core.contracts.v1.enums import ProposalProvenance, StageStatus


class ConstraintEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    constraint: str
    satisfied: bool
    evidence: str


class PatternMatch(BaseModel):
    """One candidate stage found by a TopologyPattern."""

    pattern_id: str
    pattern_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    rails: dict[str, str] = Field(default_factory=dict)  # rail name -> net name
    roles: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # role -> refdes tuple
    evidence: list[ConstraintEvidence] = Field(default_factory=list)
    unmet: list[str] = Field(default_factory=list)


class Rail(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    rail: str  # vin / sw / vout / gnd / ...
    net_name: str
    provenance: ProposalProvenance = ProposalProvenance.PROPOSED


class RoleAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    refdes: str
    role: str
    rail: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    evidence: str = ""
    provenance: ProposalProvenance = ProposalProvenance.PROPOSED


class RoleProposal(BaseModel):
    pattern_id: str
    pattern_version: str
    confidence: float
    rails: list[Rail]
    assignments: list[RoleAssignment]


class RoleEdit(BaseModel):
    model_config = ConfigDict(frozen=True)

    refdes: str
    role: str
    rail: str | None = None


class Stage(BaseModel):
    id: int | None = None
    pattern_id: str
    pattern_version: str
    match_confidence: float
    netlist_hash: str | None = None
    status: StageStatus = StageStatus.PROPOSED
    rails: list[Rail] = Field(default_factory=list)
    assignments: list[RoleAssignment] = Field(default_factory=list)


class RoleMap(BaseModel):
    """Confirmed roles keyed for M2: role -> refdes list; rail -> net name."""

    roles: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    rails: dict[str, str] = Field(default_factory=dict)

    def parts_with_role(self, role: str) -> tuple[str, ...]:
        return self.roles.get(role, ())
