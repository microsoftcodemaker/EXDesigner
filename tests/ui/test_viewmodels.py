"""View-models run without Qt (MOD-07). This file must import nothing from PySide6."""

from __future__ import annotations

from dfr.core.contracts import Diagnostic, Severity
from dfr.core.db.repos import DesignRepo
from dfr.core.registry import discover
from dfr.ui.viewmodels.observable import Property, Signal
from dfr.ui.viewmodels.shell import STEPS, Selection, ShellViewModel, StepStatus, TierMix


def test_signal_isolates_listener_errors() -> None:
    sig: Signal[int] = Signal()
    seen: list[int] = []

    def boom(_: int) -> None:
        raise RuntimeError("x")

    sig.connect(boom)
    off = sig.connect(seen.append)
    sig.emit(1)
    assert seen == [1] and len(sig) == 2
    off()
    sig.emit(2)
    assert seen == [1]


def test_property_emits_only_on_change() -> None:
    p = Property(1)
    seen: list[int] = []
    p.changed.connect(seen.append)
    p.set(1)
    p.set(2)
    assert seen == [2] and p.value == 2


def test_tier_mix_label() -> None:
    assert TierMix().label == "no stress values"
    assert TierMix(t1=3, t2=1).label == "T1 3  T2 1  (25% T2)"


def test_shell_vm_open_design_and_steps(clock) -> None:
    vm = ShellViewModel(registry=discover(entry_points=False), clock=clock)
    try:
        assert vm.step_status["design"] is StepStatus.READY
        assert all(vm.step_status[k] is StepStatus.NOT_STARTED for k, _ in STEPS[1:])
        statuses: list[dict[str, StepStatus]] = []
        vm.steps_changed.connect(statuses.append)

        repo = DesignRepo(vm.session, clock)
        d = repo.create("VM design", topology_template="buck_integrated")
        repo.new_version(d.id)
        vm.open_design(d.id)
        assert vm.design_id.value == d.id and vm.design_version_id.value is not None
        assert (
            vm.step_status["design"] is StepStatus.DONE
            and vm.step_status["parts"] is StepStatus.READY
        )
        assert statuses and vm.status_text.value.startswith("VM design")
        sel = vm.selection.value
        assert isinstance(sel, Selection) and sel.kind == "design" and sel.title == "VM design"

        vm.set_step("analyze", StepStatus.DONE)
        vm.set_step("report", StepStatus.DONE)
        vm.mark_downstream_stale("circuit")
        assert (
            vm.step_status["analyze"] is StepStatus.STALE
            and vm.step_status["report"] is StepStatus.STALE
        )
        assert vm.step_status["design"] is StepStatus.DONE

        msgs: list[list[Diagnostic]] = []
        vm.messages_changed.connect(msgs.append)
        vm.post(Diagnostic(code="X", severity=Severity.WARNING, message="m"))
        assert msgs[-1][-1].code == "X"
        vm.clear_messages()
        assert vm.messages == []
        vm.open_design(9999)
        assert vm.messages[-1].code == "UI_NO_DESIGN"
        vm.toggle_palette()
        assert vm.palette_name.value == "light"
    finally:
        vm.close()
