"""Boost and inverting buck-boost templates (PRD 3.2, T26).

``compute_full(params)`` returns StressSpecs keyed by role for ``vin_max`` and ``vin_min`` at
Iout_max (the boost's inductor and switch currents peak at Vin_min). Rows for the main switch
go to the discrete switch role *and* to ``ic`` (integrated switch); M2 binds only the roles
the confirmed stage has. ``synchronous`` = 0 (M2 sets it when a catch diode is assigned)
selects diode rows, otherwise the synchronous-rectifier FET rows.

params (SI): vin_min, vin_max, vout (magnitude for buck-boost), iout_max, fsw, t_ambient, L;
optional cout, esr_eq, dcr, vd (rectifier Vf), rds_hs, rds_ls (FET Rds_on at 25 C).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from dfr.core.contracts import Diagnostic, Severity, Stat, StressSpec
from dfr.core.extension import TopologyTemplate
from dfr.topologies.boost.equations import (
    BoostInputError,
    BoostPoint,
    boost_point,
    buck_boost_point,
)
from dfr.topologies.boost.pattern import BOOST, PATTERN_VERSION

SCENARIOS = ("vin_max", "vin_min")
REQUIRED = ("vin_min", "vin_max", "vout", "iout_max", "fsw", "t_ambient", "L")
MODULE = "topology_boost"


@dataclass
class TemplateOutput:
    stress: dict[str, list[StressSpec]] = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, role: str, spec: StressSpec) -> None:
        self.stress.setdefault(role, []).append(spec)


class BoostFamilyTemplate(TopologyTemplate):
    version = PATTERN_VERSION
    required_inputs = REQUIRED
    # M2 prompt text for ``needs`` this template raises (role, param, stat, reason, how)
    prompt_specs = {
        "vd": (
            "catch_diode",
            "v_dc",
            "dc",
            "rectifier diode forward drop missing: duty cycle and Vds use an ideal diode",
            "Vf at the inductor average current from the diode datasheet",
        ),
    }

    def __init__(self, kind: str) -> None:
        self.id = self.pattern_id = kind
        self.inverting = kind != BOOST
        main = "high_side_switch" if self.inverting else "low_side_switch"
        sync = "low_side_switch" if self.inverting else "high_side_switch"
        self.main_role, self.sync_role = main, sync
        self.roles = ("ic", "inductor", main, sync, "catch_diode", "output_cap", "input_cap")

    def _point(self, params: Mapping[str, float], vin: float, vf: float) -> BoostPoint:
        fn = buck_boost_point if self.inverting else boost_point
        return fn(
            vin=vin,
            vout=params["vout"],
            iout=params["iout_max"],
            fsw=params["fsw"],
            inductance=params["L"],
            cout=params.get("cout"),
            esr=params.get("esr_eq"),
            dcr=params.get("dcr"),
            vf=vf,
        )

    def validity_checks(self, params: Mapping[str, float]) -> list[Diagnostic]:
        missing = [k for k in REQUIRED if k not in params]
        if missing:
            return [_diag("TEMPLATE_MISSING_INPUT", f"missing: {', '.join(missing)}", True)]
        out: list[Diagnostic] = []
        for key in SCENARIOS:
            try:
                self._point(params, params[key], params.get("vd", 0.0))
            except BoostInputError as exc:
                out.append(_diag("TEMPLATE_INVALID_INPUT", f"{key}: {exc}", True))
        if params.get("cout", 0) <= 0:
            out.append(
                _diag("TEMPLATE_NO_COUT", "Cout missing; output ripple voltage not computed")
            )
        return out

    def compute(self, params: Mapping[str, float]) -> dict[str, list[StressSpec]]:
        return self.compute_full(params).stress

    def compute_full(self, params: Mapping[str, float]) -> TemplateOutput:
        out = TemplateOutput(diagnostics=self.validity_checks(params))
        if any(d.severity is Severity.ERROR for d in out.diagnostics):
            return out
        synchronous = bool(params.get("synchronous", 1.0))
        vf = 0.0 if synchronous else params.get("vd", 0.0)
        if not synchronous and "vd" not in params:
            out.needs.append("vd")
            out.diagnostics.append(
                _diag("TEMPLATE_NEEDS_VD", "rectifier Vf missing; using an ideal diode")
            )
        for sc in SCENARIOS:
            self._emit(out, self._point(params, params[sc], vf), sc, params, synchronous)
        return out

    def _emit(
        self,
        out: TemplateOutput,
        p: BoostPoint,
        sc: str,
        params: Mapping[str, float],
        synchronous: bool,
    ) -> None:
        if not p.ccm:
            out.diagnostics.append(
                _diag("TEMPLATE_DCM", f"{sc}: DCM at Iout_max; CCM equations extrapolated")
            )
        elif p.near_boundary:
            out.diagnostics.append(
                _diag(
                    "TEMPLATE_NEAR_BOUNDARY",
                    f"{sc}: within 20 % of the CCM/DCM edge (margin {p.boundary_margin:.2f})",
                )
            )
        out.add("inductor", _s("i_peak", p.il_peak, "A", Stat.PEAK, sc))
        out.add("inductor", _s("i_rms", p.il_rms, "A", Stat.RMS, sc))
        out.add("inductor", _s("i_ripple_pp", p.ripple_pp, "A", Stat.PEAK, sc, "peak-to-peak"))
        if p.p_inductor_cu is not None:
            out.add("inductor", _s("p_loss", p.p_inductor_cu, "W", Stat.AVG, sc, "copper only"))
        else:
            out.needs.append("dcr")
        split = "split equally among {} caps"
        out.add("output_cap", _s("i_rms", p.i_cout_rms, "A", Stat.RMS, sc, split.format("output")))
        out.add("output_cap", _s("v_dc", p.vout, "V", Stat.DC, sc))
        if p.v_out_ripple is not None:
            out.add("output_cap", _s("v_ripple_pp", p.v_out_ripple, "V", Stat.PEAK, sc))
        out.add("input_cap", _s("i_rms", p.i_cin_rms, "A", Stat.RMS, sc, split.format("input")))
        out.add("input_cap", _s("v_dc", p.vin, "V", Stat.DC, sc))

        ring = "ideal; ringing not included (F4)"
        main_rds = "rds_hs" if self.inverting else "rds_ls"
        for role in (self.main_role, "ic"):
            out.add(role, _s("i_rms", p.i_sw_rms, "A", Stat.RMS, sc))
            out.add(role, _s("i_peak", p.il_peak, "A", Stat.PEAK, sc, "compare with current limit"))
            out.add(role, _s("v_peak", p.v_sw_max, "V", Stat.PEAK, sc, ring))
        if main_rds in params:
            loss = p.i_sw_rms**2 * params[main_rds]
            out.add(self.main_role, _s("p_loss", loss, "W", Stat.AVG, sc, "conduction at 25 C"))
        if synchronous:
            sync_rds = "rds_ls" if self.inverting else "rds_hs"
            out.add(self.sync_role, _s("i_rms", p.i_d_rms, "A", Stat.RMS, sc))
            out.add(self.sync_role, _s("i_peak", p.il_peak, "A", Stat.PEAK, sc))
            out.add(self.sync_role, _s("v_peak", p.v_d_max, "V", Stat.PEAK, sc, ring))
            if sync_rds in params:
                loss = p.i_d_rms**2 * params[sync_rds]
                out.add(self.sync_role, _s("p_loss", loss, "W", Stat.AVG, sc, "conduction at 25 C"))
        else:
            out.add("catch_diode", _s("i_avg", p.i_d_avg, "A", Stat.AVG, sc))
            out.add("catch_diode", _s("i_rms", p.i_d_rms, "A", Stat.RMS, sc))
            out.add("catch_diode", _s("i_peak", p.il_peak, "A", Stat.PEAK, sc))
            out.add("catch_diode", _s("v_peak", p.v_d_max, "V", Stat.PEAK, sc, ring))


def _s(  # noqa: PLR0917 - mirrors StressSpec field order
    param: str, value: float, unit: str, stat: Stat, scenario: str, note: str | None = None
) -> StressSpec:
    return StressSpec(param=param, value=value, unit=unit, stat=stat, scenario=scenario, note=note)


def _diag(code: str, message: str, error: bool = False) -> Diagnostic:
    sev = Severity.ERROR if error else Severity.WARNING
    return Diagnostic(code=code, severity=sev, message=message, module=MODULE)
