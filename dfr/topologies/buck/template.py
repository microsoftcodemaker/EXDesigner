"""Buck templates: ``buck`` (discrete switches) and ``buck_integrated`` (PRD 3.2).

``compute(params)`` returns StressSpecs keyed by role for the scenarios ``vin_max`` and
``vin_min`` (both at Iout_max). M2 binds them to parts, infers L/Cout from roles, stamps
provenance and raises ValuePrompts for anything listed in ``needs``.

params (SI):
    vin_min, vin_max, vout, iout_max, fsw, t_ambient      (converter spec, OPC-11)
    L, cout, esr_eq, dcr                                   (inferred from BOM, OPC-12)
    synchronous (1/0), vd (catch diode drop, async only)
    rds_hs, rds_ls, p_sw, eta, theta_ja                    (integrated IC loss, OPC-14)
    rds_hs / rds_ls also used for discrete FET conduction loss when present
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from dfr.core.contracts import Diagnostic, Severity, Stat, StressSpec
from dfr.core.extension import TopologyTemplate
from dfr.topologies.buck.equations import BuckInputError, BuckPoint, buck_point
from dfr.topologies.buck.pattern import PATTERN_ID, PATTERN_VERSION

SCENARIOS = (("vin_max", "vin_max"), ("vin_min", "vin_min"))
REQUIRED = ("vin_min", "vin_max", "vout", "iout_max", "fsw", "t_ambient", "L")


@dataclass
class TemplateOutput:
    stress: dict[str, list[StressSpec]] = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)  # parameter names M2 should prompt for
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, role: str, spec: StressSpec) -> None:
        self.stress.setdefault(role, []).append(spec)


class BuckTemplate(TopologyTemplate):
    version = PATTERN_VERSION
    required_inputs = REQUIRED

    def __init__(self, integrated: bool) -> None:
        self.integrated = integrated
        self.id = f"{PATTERN_ID}_integrated" if integrated else PATTERN_ID
        self.pattern_id = self.id
        self.roles = (
            ("ic", "inductor", "output_cap", "input_cap", "catch_diode")
            if integrated
            else (
                "high_side_switch",
                "low_side_switch",
                "catch_diode",
                "inductor",
                "output_cap",
                "input_cap",
            )
        )

    # ----------------------------------------------------------------- interface
    def validity_checks(self, params: Mapping[str, float]) -> list[Diagnostic]:
        out: list[Diagnostic] = []
        missing = [k for k in REQUIRED if k not in params]
        if missing:
            out.append(
                _diag("TEMPLATE_MISSING_INPUT", f"missing: {', '.join(missing)}", Severity.ERROR)
            )
            return out
        for vin_key in ("vin_min", "vin_max"):
            try:
                buck_point(
                    vin=params[vin_key],
                    vout=params["vout"],
                    iout=params["iout_max"],
                    fsw=params["fsw"],
                    inductance=params["L"],
                )
            except BuckInputError as exc:
                out.append(_diag("TEMPLATE_INVALID_INPUT", f"{vin_key}: {exc}", Severity.ERROR))
        if params.get("cout", 0) <= 0:
            out.append(
                _diag(
                    "TEMPLATE_NO_COUT", "Cout missing or zero; output ripple voltage not computed"
                )
            )
        return out

    def compute(self, params: Mapping[str, float]) -> dict[str, list[StressSpec]]:
        return self.compute_full(params).stress

    # ----------------------------------------------------------------- full output
    def compute_full(self, params: Mapping[str, float]) -> TemplateOutput:
        out = TemplateOutput(diagnostics=self.validity_checks(params))
        if any(d.severity is Severity.ERROR for d in out.diagnostics):
            return out
        synchronous = bool(params.get("synchronous", 1.0))
        vd = params.get("vd") if not synchronous else None
        if not synchronous and vd is None:
            out.needs.append("vd")
            out.diagnostics.append(
                _diag(
                    "TEMPLATE_NEEDS_VD",
                    "asynchronous buck: catch-diode Vf needed; using ideal diode",
                )
            )
        for scenario, vin_key in SCENARIOS:
            point = buck_point(
                vin=params[vin_key],
                vout=params["vout"],
                iout=params["iout_max"],
                fsw=params["fsw"],
                inductance=params["L"],
                cout=params.get("cout"),
                esr=params.get("esr_eq"),
                dcr=params.get("dcr"),
                diode_drop=vd,
            )
            self._emit_point(out, point, scenario, params, synchronous)
        return out

    def _emit_point(
        self,
        out: TemplateOutput,
        p: BuckPoint,
        sc: str,
        params: Mapping[str, float],
        synchronous: bool,
    ) -> None:
        if not p.ccm:
            out.diagnostics.append(
                _diag(
                    "TEMPLATE_DCM",
                    f"{sc}: DCM at Iout_max (DIL/2 = {p.ripple_pp / 2:.3g} A > Iout); "
                    "CCM equations extrapolated",
                )
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
            out.add(
                "inductor", _s("p_loss", p.p_inductor_cu, "W", Stat.AVG, sc, "copper loss only")
            )
        else:
            out.needs.append("dcr")
        out.add(
            "output_cap",
            _s("i_rms", p.i_cout_rms, "A", Stat.RMS, sc, "total; split equally among output caps"),
        )
        out.add("output_cap", _s("v_dc", p.vout, "V", Stat.DC, sc))
        if p.v_out_ripple is not None:
            out.add(
                "output_cap", _s("v_ripple_pp", p.v_out_ripple, "V", Stat.PEAK, sc, "peak-to-peak")
            )
        out.add(
            "input_cap",
            _s(
                "i_rms",
                p.i_cin_rms,
                "A",
                Stat.RMS,
                sc,
                "ideal source; split equally among input caps",
            ),
        )
        out.add("input_cap", _s("v_dc", p.vin, "V", Stat.DC, sc))

        if self.integrated:
            self._emit_ic(out, p, sc, params, synchronous)
        else:
            self._emit_discrete(out, p, sc, params, synchronous)
        if not synchronous:
            out.add("catch_diode", _s("i_avg", p.i_ls_avg, "A", Stat.AVG, sc))
            out.add("catch_diode", _s("i_rms", p.i_ls_rms, "A", Stat.RMS, sc))
            out.add(
                "catch_diode",
                _s("v_peak", p.v_sw_max, "V", Stat.PEAK, sc, "ideal; ringing not included (F4)"),
            )

    def _emit_discrete(
        self,
        out: TemplateOutput,
        p: BuckPoint,
        sc: str,
        params: Mapping[str, float],
        synchronous: bool,
    ) -> None:
        out.add("high_side_switch", _s("i_rms", p.i_hs_rms, "A", Stat.RMS, sc))
        out.add("high_side_switch", _s("i_peak", p.il_peak, "A", Stat.PEAK, sc))
        out.add(
            "high_side_switch",
            _s("v_peak", p.v_sw_max, "V", Stat.PEAK, sc, "ideal; ringing not included (F4)"),
        )
        if "rds_hs" in params:
            out.add(
                "high_side_switch",
                _s(
                    "p_loss",
                    p.i_hs_rms**2 * params["rds_hs"],
                    "W",
                    Stat.AVG,
                    sc,
                    "conduction only at 25 C; M6 iterates Rds_on(Tj)",
                ),
            )
        if synchronous:
            out.add("low_side_switch", _s("i_rms", p.i_ls_rms, "A", Stat.RMS, sc))
            out.add("low_side_switch", _s("i_peak", p.il_peak, "A", Stat.PEAK, sc))
            out.add(
                "low_side_switch",
                _s("v_peak", p.v_sw_max, "V", Stat.PEAK, sc, "ideal; ringing not included (F4)"),
            )
            if "rds_ls" in params:
                out.add(
                    "low_side_switch",
                    _s(
                        "p_loss",
                        p.i_ls_rms**2 * params["rds_ls"],
                        "W",
                        Stat.AVG,
                        sc,
                        "conduction only at 25 C",
                    ),
                )

    def _emit_ic(
        self,
        out: TemplateOutput,
        p: BuckPoint,
        sc: str,
        params: Mapping[str, float],
        synchronous: bool,
    ) -> None:
        """Stress rows attach to the IC part (OPC-14)."""
        out.add("ic", _s("i_rms_hs", p.i_hs_rms, "A", Stat.RMS, sc))
        if synchronous:
            out.add("ic", _s("i_rms_ls", p.i_ls_rms, "A", Stat.RMS, sc))
        out.add("ic", _s("i_peak", p.il_peak, "A", Stat.PEAK, sc, "compare with current limit"))
        out.add(
            "ic", _s("v_peak", p.vin, "V", Stat.PEAK, sc, "Vin at pin; ringing not included (F4)")
        )
        out.add("ic", _s("i_out", p.iout, "A", Stat.DC, sc, "compare with rated output current"))

        p_ic: float | None = None
        note = ""
        if "rds_hs" in params and (not synchronous or "rds_ls" in params):
            p_cond = p.i_hs_rms**2 * params["rds_hs"] + (
                p.i_ls_rms**2 * params["rds_ls"] if synchronous else 0.0
            )
            if "p_sw" in params:
                p_ic, note = p_cond + params["p_sw"], "option 1: internal Rds_on at 25 C + P_sw"
            else:
                p_ic, note = p_cond, "option 1: internal Rds_on at 25 C; P_sw missing"
                out.needs.append("p_sw")
        elif "eta" in params and 0 < params["eta"] < 1:
            p_out = p.vout * p.iout
            p_ic = p_out * (1.0 / params["eta"] - 1.0) - (p.p_inductor_cu or 0.0)
            note = (
                "option 2: from datasheet efficiency; inductor copper loss subtracted "
                "(verify curve basis)"
            )
        if p_ic is not None:
            out.add("ic", _s("p_loss", max(p_ic, 0.0), "W", Stat.AVG, sc, note))
        else:
            out.needs.append("p_ic")
            out.diagnostics.append(
                _diag(
                    "TEMPLATE_NEEDS_IC_LOSS",
                    f"{sc}: neither internal Rds_on nor efficiency available; "
                    "IC loss prompted, never assumed",
                )
            )


def _s(  # noqa: PLR0917 - positional mirrors StressSpec field order
    param: str, value: float, unit: str, stat: Stat, scenario: str, note: str | None = None
) -> StressSpec:
    return StressSpec(param=param, value=value, unit=unit, stat=stat, scenario=scenario, note=note)


def _diag(code: str, message: str, severity: Severity = Severity.WARNING) -> Diagnostic:
    return Diagnostic(code=code, severity=severity, message=message, module="topology_buck")
