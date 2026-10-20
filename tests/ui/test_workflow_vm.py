"""Tiered workflow through the Workspace view-model without Qt (PRD 2.6 state machine)."""

from __future__ import annotations

import pytest

pytest.importorskip("dfr.topologies.buck")

from dfr.core.contracts import ConverterSpec, SessionState, Source, Tier
from dfr.core.db.repos import RunRepo, StressRepo
from dfr.core.registry import discover
from dfr.ui.viewmodels.shell import ShellViewModel, StepStatus
from tests.conftest import FIXTURES

BOM = FIXTURES / "design_c" / "design_c.BomDoc"
NET = FIXTURES / "design_c" / "design_c_protel.net"
SPEC = ConverterSpec(vin_min=7, vin_max=22, vout=3.3, iout_max=3.25, fsw=400e3, t_ambient=20)


def test_workflow_states_t1_t2_rerun_final(clock) -> None:
    vm = ShellViewModel(registry=discover(entry_points=False), clock=clock)
    ws = vm.workspace
    states: list[SessionState] = []
    vm.workflow_state.changed.connect(states.append)
    try:
        assert ws.rerun() is None and vm.messages[-1].code == "UI_NO_RUN"
        assert ws.import_files("Design C", BOM, NET, "buck_integrated")
        assert vm.workflow_state.value is SessionState.DRAFT
        assert ws.run_match("buck_integrated") is not None and ws.confirm([]) is not None
        assert vm.workflow_state.value is SessionState.CIRCUIT_CONFIRMED
        ws.set_spec(SPEC, {})
        out = ws.run_tier1()
        assert out is not None and out.ok and out.run.tier_level is Tier.T1
        assert vm.workflow_state.value is SessionState.TRIAGED
        assert vm.step_status["refine"] is StepStatus.READY
        assert SessionState.T1_RUNNING in states
        vid = vm.design_version_id.value
        assert vid is not None

        # Tier 2 by CSV: a bad file changes nothing; a good one queues a re-run.
        bad = ws.import_t2_csv(
            "refdes,param,stat,value,unit,source\nZZ,x,peak,1,A,measured\n", "bad.csv"
        )
        assert bad is not None and not bad.ok and vm.workflow_state.value is SessionState.TRIAGED
        good = ws.import_t2_csv(
            "refdes,param,stat,scenario,value,unit,source,tool\n"
            "U3,p_loss,avg,vin_max,0.9,W,measured,bench\n"
            "L1,i_peak,peak,vin_max,3.9,A,measured,probe\n",
            "bench.csv",
        )
        assert good is not None and good.ok and len(good.stored) == 2
        assert good.answered_prompt_ids  # the M2 IC-loss prompt is answered by the CSV row
        assert vm.workflow_state.value is SessionState.T2_QUEUED
        assert vm.step_status["analyze"] is StepStatus.STALE
        assert vm.tier_mix.value.t2 == 2

        out2 = ws.rerun()
        assert out2 is not None and out2.ok and out2.run.tier_level is Tier.T2
        assert out2.run.parent_run_id == out.run.id
        assert vm.workflow_state.value is SessionState.TRIAGED and SessionState.RERUN in states
        chain = RunRepo(vm.session, clock).chain(out2.run.id)
        assert [r.id for r in chain] == [out.run.id, out2.run.id]
        eff = out2.context.get("effective_stress")
        l1 = next(p for p in ws.parts() if p.refdes == "L1")
        assert eff[(l1.id, "i_peak", "vin_max")].tier is Tier.T2
        assert eff[(l1.id, "i_peak", "vin_max")].source is Source.MEASURED
        if "m3_triage" in vm.present_modules:  # the suite also runs with M3 deleted
            assert out2.context.get_or("refinement", []), "triage ran on the re-run"

        ws.mark_final()
        assert vm.workflow_state.value is SessionState.FINAL
        assert vm.step_status["refine"] is StepStatus.DONE
        assert len(StressRepo(vm.session, clock).for_version(vid)) >= 40
    finally:
        vm.close()
