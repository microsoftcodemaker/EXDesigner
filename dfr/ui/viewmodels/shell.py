"""Shell view-model: workspace state, stepper, selection, messages (PRD 4.1 navigation).

Owns the engine session, the registry and the open design. Screens read from here and call
registry services; the shell never imports a module package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dfr.core.contracts import Diagnostic, SessionState, Severity
from dfr.core.db import migrate
from dfr.core.db.base import MEMORY_URL, create_sqlite_engine, sqlite_url
from dfr.core.db.repos import DesignRepo, RunRepo, StressRepo
from dfr.core.db.session import make_session_factory
from dfr.core.ports import Clock, SystemClock
from dfr.core.registry import DiscoveryResult, discover
from dfr.ui.viewmodels.observable import Property, Signal
from dfr.ui.viewmodels.workspace import Workspace

STEPS: tuple[tuple[str, str], ...] = (
    ("design", "Design"),
    ("parts", "Parts"),
    ("circuit", "Circuit"),
    ("conditions", "Conditions"),
    ("analyze", "Analyze"),
    ("refine", "Refine"),
    ("report", "Report"),
)


class StepStatus(StrEnum):
    NOT_STARTED = "not started"
    READY = "ready"
    DONE = "done"
    STALE = "stale"


@dataclass
class Selection:
    """What the Properties panel shows. ``kind`` is 'part', 'stress', 'role', 'run', ..."""

    kind: str
    title: str
    fields: list[tuple[str, str]] = field(default_factory=list)
    payload: Any = None


@dataclass
class TierMix:
    t1: int = 0
    t2: int = 0

    @property
    def label(self) -> str:
        total = self.t1 + self.t2
        if not total:
            return "no stress values"
        return f"T1 {self.t1}  T2 {self.t2}  ({100 * self.t2 // total}% T2)"


class ShellViewModel:
    def __init__(
        self,
        *,
        db_path: Path | None = None,
        registry: DiscoveryResult | None = None,
        clock: Clock | None = None,
        engine: Engine | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self.registry = registry or discover()
        self.engine = engine or create_sqlite_engine(sqlite_url(db_path) if db_path else MEMORY_URL)
        self.orphans = migrate.upgrade_all(self.engine, self.registry.modules)
        self._factory = make_session_factory(self.engine)
        self.session: Session = self._factory()

        self.design_id: Property[int | None] = Property(None)
        self.design_version_id: Property[int | None] = Property(None)
        self.current_run_id: Property[int | None] = Property(None)
        self.palette_name: Property[str] = Property("dark")
        self.active_step: Property[str] = Property("design")
        self.selection: Property[Selection | None] = Property(None)
        # PRD 2.6 tiered-workflow state machine; the stepper is a coarser view of it.
        self.workflow_state: Property[SessionState] = Property(SessionState.DRAFT)
        self.step_status: dict[str, StepStatus] = {k: StepStatus.NOT_STARTED for k, _ in STEPS}
        self.step_status["design"] = StepStatus.READY
        self.steps_changed: Signal[dict[str, StepStatus]] = Signal()
        self.messages: list[Diagnostic] = []
        self.messages_changed: Signal[list[Diagnostic]] = Signal()
        self.status_text: Property[str] = Property("Ready")
        self.tier_mix: Property[TierMix] = Property(TierMix())
        self.navigate: Signal[str] = Signal()  # screen id a view asks the shell to open
        self.workspace = Workspace(self)

        for d in self.registry.diagnostics:
            self.messages.append(d)
        for rev in self.orphans:
            self.messages.append(
                Diagnostic(
                    code="DB_ORPHAN_BRANCH",
                    severity=Severity.INFO,
                    module="shell",
                    message=f"database has tables from an uninstalled module ({rev}); kept",
                )
            )

    # ----------------------------------------------------------------- lifecycle
    def commit(self) -> None:
        self.session.commit()

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()

    # ----------------------------------------------------------------- design
    def open_design(self, design_id: int) -> None:
        repo = DesignRepo(self.session, self.clock)
        design = repo.get(design_id)
        if design is None:
            self.post(
                Diagnostic(
                    code="UI_NO_DESIGN",
                    severity=Severity.ERROR,
                    module="shell",
                    message=f"design {design_id} not found",
                )
            )
            return
        version = repo.latest_version(design_id)
        if design_id != self.design_id.value:
            self.workflow_state.set(SessionState.DRAFT)
        self.design_id.set(design_id)
        self.design_version_id.set(version.id if version else None)
        self.set_step("design", StepStatus.DONE)
        self.set_step("parts", StepStatus.READY if version else StepStatus.NOT_STARTED)
        self.refresh_runs()
        self.workspace.reload_from_db()
        self.status_text.set(f"{design.name}  v{version.version_no if version else '-'}")
        self.select(
            Selection(
                "design",
                design.name,
                [
                    ("Design id", str(design.id)),
                    ("Topology", design.topology_template or "-"),
                    ("Version", str(version.version_no) if version else "-"),
                    ("Netlist hash", (version.netlist_hash or "-")[:12] if version else "-"),
                ],
                payload=design,
            )
        )

    def refresh_runs(self) -> None:
        vid = self.design_version_id.value
        if vid is None:
            self.current_run_id.set(None)
            self.tier_mix.set(TierMix())
            return
        runs = RunRepo(self.session, self.clock).for_version(vid)
        self.current_run_id.set(runs[-1].id if runs else None)
        values = StressRepo(self.session, self.clock).for_version(vid)
        self.tier_mix.set(
            TierMix(
                t1=sum(int(v.tier) == 1 for v in values), t2=sum(int(v.tier) == 2 for v in values)
            )
        )
        if runs:
            self.set_step("analyze", StepStatus.DONE)
            self.set_step("refine", StepStatus.READY)
            self.set_step("report", StepStatus.READY)
            if self.workflow_state.value in (SessionState.DRAFT, SessionState.CIRCUIT_CONFIRMED):
                self.workflow_state.set(SessionState.TRIAGED)

    # ----------------------------------------------------------------- stepper
    def set_step(self, step: str, status: StepStatus) -> None:
        if self.step_status.get(step) != status:
            self.step_status[step] = status
            self.steps_changed.emit(dict(self.step_status))

    def mark_downstream_stale(self, from_step: str) -> None:
        """An upstream change (new netlist, edited roles) invalidates everything after it."""
        keys = [k for k, _ in STEPS]
        for k in keys[keys.index(from_step) + 1 :]:
            if self.step_status[k] is StepStatus.DONE:
                self.set_step(k, StepStatus.STALE)

    # ----------------------------------------------------------------- selection / messages
    def select(self, selection: Selection | None) -> None:
        self.selection.set(selection)

    def post(self, *diagnostics: Diagnostic) -> None:
        self.messages.extend(diagnostics)
        self.messages_changed.emit(list(self.messages))

    def clear_messages(self) -> None:
        self.messages.clear()
        self.messages_changed.emit([])

    def toggle_palette(self) -> None:
        self.palette_name.set("light" if self.palette_name.value == "dark" else "dark")

    @property
    def present_modules(self) -> list[str]:
        return [m.id for m in self.registry.modules]
