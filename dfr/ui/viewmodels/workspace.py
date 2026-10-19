"""Workspace: the in-progress analysis session shared by the screens (plain Python, no Qt).

Holds what the stepper needs between screens: the imported design, the proposed/confirmed
stage, the converter spec, the last run outcome. All engine calls go through registry
services so the view-models never import a module package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dfr.core.contracts import (
    ConverterSpec,
    Diagnostic,
    PinoutRequest,
    RoleEdit,
    RoleProposal,
    RunConfig,
    Severity,
    Stage,
    StageStatus,
)
from dfr.core.db.repos import DesignRepo, PartRepo, StageRepo
from dfr.ui.viewmodels.observable import Signal


@dataclass
class MatchState:
    topology: str
    proposal: RoleProposal | None
    candidates: list[Any]
    inferred_pins: dict[str, dict[str, str]]
    diagnostics: list[Diagnostic]


class Workspace:
    """Owned by ShellViewModel; one per open design version."""

    def __init__(self, shell: Any) -> None:  # ShellViewModel (avoid import cycle)
        self.shell = shell
        self.imported: Any | None = None  # dfr.app.workflow.ImportOutcome
        self.pinout_requests: list[PinoutRequest] = []
        self.match: MatchState | None = None
        self.stage: Stage | None = None
        self.spec: ConverterSpec | None = None
        self.spec_overrides: dict[str, float] = {}
        self.last_outcome: Any | None = None  # dfr.app.orchestrator.RunOutcome
        self.changed: Signal[str] = Signal()  # emits the name of what changed

    # ----------------------------------------------------------------- helpers
    @property
    def registry(self) -> Any:
        return self.shell.registry

    @property
    def session(self) -> Any:
        return self.shell.session

    def _post(self, diags: list[Diagnostic]) -> None:
        if diags:
            self.shell.post(*diags)

    def topologies(self) -> list[str]:
        patterns: dict[str, Any] = {}
        for provider in self.registry.services_named("topology.patterns"):
            patterns.update(provider())
        return sorted(patterns)

    # ----------------------------------------------------------------- import (T20)
    def import_files(self, name: str, bom: Path, netlist: Path, topology: str) -> bool:
        from dfr.app.workflow import import_design  # noqa: PLC0415 - app layer is below ui
        from dfr.ui.viewmodels.shell import StepStatus  # noqa: PLC0415

        try:
            out = import_design(
                self.session,
                self.registry,
                self.shell.clock,
                name=name,
                bom_path=bom,
                netlist_path=netlist,
                topology=topology,
            )
        except Exception as exc:
            self.shell.post(
                Diagnostic(
                    code="UI_IMPORT_FAILED", severity=Severity.ERROR, module="ui", message=repr(exc)
                )
            )
            return False
        self.shell.commit()
        self.imported = out
        self.pinout_requests = list(out.pinout_requests)
        self.match = None
        self.stage = None
        self.last_outcome = None
        self._post(out.diagnostics)
        self.shell.open_design(out.design_id)
        self.shell.set_step("parts", StepStatus.DONE)
        self.shell.set_step("circuit", StepStatus.READY)
        self.changed.emit("imported")
        return True

    def reload_from_db(self) -> None:
        """When a design is opened from Home, rebuild what we can from stored rows."""
        from dfr.ui.viewmodels.shell import StepStatus  # noqa: PLC0415

        vid = self.shell.design_version_id.value
        if vid is None:
            return
        stages = StageRepo(self.session, self.shell.clock).for_version(vid)
        confirmed = [s for s in stages if s.status is StageStatus.CONFIRMED]
        self.stage = confirmed[-1] if confirmed else None
        if self.stage is not None:
            self.shell.set_step("circuit", StepStatus.DONE)
            self.shell.set_step("conditions", StepStatus.READY)
        self.changed.emit("reloaded")

    def parts(self) -> list[Any]:
        vid = self.shell.design_version_id.value
        return PartRepo(self.session).for_version(vid) if vid is not None else []

    # ----------------------------------------------------------------- circuit (T21)
    def run_match(self, topology: str, chosen_index: int = 0) -> MatchState | None:
        if self.imported is None:
            self.shell.post(
                Diagnostic(
                    code="UI_NO_IMPORT",
                    severity=Severity.ERROR,
                    module="ui",
                    message="import a BOM and netlist first",
                )
            )
            return None
        svc = self.registry.service
        patterns: dict[str, Any] = {}
        for provider in self.registry.services_named("topology.patterns"):
            patterns.update(provider())
        inference: dict[str, Any] = {}
        for provider in self.registry.services_named("topology.inference"):
            inference.update(provider())
        out = svc("match_topology")(
            self.imported._graph,
            self.imported._parts,
            topology,
            patterns,
            inference=inference,
            chosen_index=chosen_index,
            bom_hints=self.imported._hints,
        )
        self.match = MatchState(
            topology, out.proposal, out.matches, out.inferred_pins, out.diagnostics
        )
        self._post(out.diagnostics)
        self.changed.emit("matched")
        return self.match

    def confirm(self, edits: list[RoleEdit]) -> Stage | None:
        from dfr.ui.viewmodels.shell import StepStatus  # noqa: PLC0415

        if self.match is None or self.match.proposal is None or self.imported is None:
            return None
        stage: Stage = self.registry.service("confirm_roles")(
            self.session,
            self.shell.clock,
            design_version_id=self.imported.design_version_id,
            proposal=self.match.proposal,
            edits=edits,
            netlist_hash=self.imported._graph.source_hash,
        )
        self.shell.commit()
        self.stage = stage
        design_id = self.shell.design_id.value
        if design_id is not None:
            d = DesignRepo(self.session, self.shell.clock).get(design_id)
            if d is not None:
                d.topology_template = self.match.topology
                self.shell.commit()
        self.shell.set_step("circuit", StepStatus.DONE)
        self.shell.set_step("conditions", StepStatus.READY)
        self.shell.mark_downstream_stale("circuit")
        self.changed.emit("confirmed")
        return stage

    def answer_pinout(self, refdes: str, pinout: dict[str, str]) -> None:
        """Save a user-entered pinout to the library and drop the request (NET-06)."""
        self.pinout_requests = [q for q in self.pinout_requests if q.refdes != refdes]
        part = next(
            (p for p in (self.imported._parts if self.imported else []) if p.refdes == refdes), None
        )
        if part is not None and self.registry.has_service("save_pinout"):
            self.registry.service("save_pinout")(self.session, self.shell.clock, part, pinout)
            self.shell.commit()
        self.changed.emit("pinout")

    # ----------------------------------------------------------------- conditions + run (T22/T23)
    def set_spec(self, spec: ConverterSpec, overrides: dict[str, float]) -> None:
        from dfr.ui.viewmodels.shell import StepStatus  # noqa: PLC0415

        self.spec = spec
        self.spec_overrides = dict(overrides)
        self.shell.set_step("conditions", StepStatus.DONE)
        self.shell.set_step("analyze", StepStatus.READY)
        self.shell.mark_downstream_stale("conditions")
        self.changed.emit("spec")

    def run_tier1(self, config: RunConfig | None = None) -> Any | None:
        from dfr.app import AnalysisInputs, run_tier1  # noqa: PLC0415
        from dfr.ui.viewmodels.shell import StepStatus  # noqa: PLC0415

        vid = self.shell.design_version_id.value
        if vid is None or self.spec is None:
            self.shell.post(
                Diagnostic(
                    code="UI_NOT_READY",
                    severity=Severity.ERROR,
                    module="ui",
                    message="open a design, confirm the circuit and enter the converter spec first",
                )
            )
            return None
        inputs = AnalysisInputs(
            vid, self.spec, config or RunConfig(), inferred_overrides=self.spec_overrides or None
        )
        outcome = run_tier1(self.session, self.registry, inputs, clock=self.shell.clock)
        self.shell.commit()
        self.last_outcome = outcome
        self._post(outcome.diagnostics)
        self.shell.refresh_runs()
        self.shell.set_step("analyze", StepStatus.DONE if outcome.ok else StepStatus.READY)
        self.changed.emit("run")
        return outcome
