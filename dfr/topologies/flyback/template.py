"""Flyback template (PRD 3.2, T27, OPC-05): CCM/DCM auto-selected per scenario, leakage spike,
boundary flag. Scenarios ``vin_max`` and ``vin_min`` at Iout_max.

params (SI): vin_min, vin_max, vout, iout_max, fsw, t_ambient; transformer ``n`` (Np/Ns) and
``lp`` (primary inductance) from the transformer ratings ``turns_ratio`` / ``l_primary`` (else
prompted, never guessed); optional ``eta`` (IC/controller rating, else the data-file default,
stated), ``vd`` (output diode Vf), ``v_spike`` (clamp-limited spike, else a fraction of
Vreflected from the data file, stated), ``rds_pri`` (primary FET Rds_on at 25 C).
Defaults: ``data/topologies/flyback.yaml`` (all verify).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from dfr.core.contracts import Diagnostic, Severity, Stat, StressSpec
from dfr.core.extension import TopologyTemplate
from dfr.topologies.flyback.equations import FlybackInputError, FlybackPoint, flyback_point
from dfr.topologies.flyback.pattern import PATTERN_ID, PATTERN_VERSION

DATA = Path(os.environ.get("DFR_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
DEFAULTS_PATH = DATA / "topologies" / "flyback.yaml"
SCENARIOS = ("vin_max", "vin_min")
REQUIRED = ("vin_min", "vin_max", "vout", "iout_max", "fsw", "t_ambient", "n", "lp")
MODULE = "topology_flyback"


@lru_cache(maxsize=1)
def load_defaults() -> dict[str, Any]:
    raw = DEFAULTS_PATH.read_bytes()
    data: dict[str, Any] = yaml.safe_load(raw)
    data["sha256"] = hashlib.sha256(raw).hexdigest()[:12]
    return data


@dataclass
class TemplateOutput:
    stress: dict[str, list[StressSpec]] = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, role: str, spec: StressSpec) -> None:
        self.stress.setdefault(role, []).append(spec)


class FlybackTemplate(TopologyTemplate):
    id = PATTERN_ID
    pattern_id = PATTERN_ID
    version = PATTERN_VERSION
    required_inputs = REQUIRED
    roles = (
        "primary_switch",
        "ic",
        "transformer",
        "output_diode",
        "output_cap",
        "input_cap",
        "sense_resistor",
    )
    # M2 reads these part ratings into params (param -> (role, rating name))
    part_inputs = {
        "n": ("transformer", "turns_ratio"),
        "lp": ("transformer", "l_primary"),
        "vd": ("output_diode", "vf"),
        "rds_pri": ("primary_switch", "rds_on"),
        "eta": ("controller", "eta"),
        "v_spike": ("clamp", "v_clamp"),
    }
    prompt_specs = {
        "n": (
            "transformer",
            "turns_ratio",
            "dc",
            "flyback turns ratio Np/Ns unknown: duty cycle, reflected voltage and every "
            "current depend on it",
            "transformer datasheet Np/Ns: add rating turns_ratio "
            "(Part Review > Edit rating, or the Catalog)",
        ),
        "lp": (
            "transformer",
            "l_primary",
            "dc",
            "primary (magnetizing) inductance unknown: ripple, peak current and CCM/DCM mode",
            "datasheet or LCR meter at fsw: add rating l_primary in H (Part Review > Edit rating)",
        ),
        "vd": (
            "output_diode",
            "v_dc",
            "dc",
            "output diode forward drop missing: an ideal diode is used",
            "Vf at the output current from the diode datasheet (rating vf)",
        ),
    }

    def validity_checks(self, params: Mapping[str, float]) -> list[Diagnostic]:
        missing = [k for k in REQUIRED if k not in params]
        if missing:
            return [
                _diag(
                    "TEMPLATE_MISSING_INPUT",
                    f"missing: {', '.join(missing)} (transformer ratings turns_ratio / l_primary)",
                    error=True,
                )
            ]
        out: list[Diagnostic] = []
        for sc in SCENARIOS:
            try:
                self._point(params, sc, {})
            except FlybackInputError as exc:
                out.append(_diag("TEMPLATE_INVALID_INPUT", f"{sc}: {exc}", error=True))
        return out

    def _point(self, params: Mapping[str, float], sc: str, notes: dict[str, str]) -> FlybackPoint:
        d = load_defaults()
        eta = params.get("eta")
        if eta is None:
            eta = float(d["eta"])
            notes["eta"] = f"eta {eta:g} assumed ({d['source']})"
        n, vf = params.get("n", 1.0), params.get("vd", 0.0)
        spike = params.get("v_spike")
        if spike is None:
            spike = float(d["v_spike_fraction"]) * n * (params["vout"] + vf)
            notes["v_spike"] = (
                f"Vspike = {float(d['v_spike_fraction']):g} x Vreflected assumed (verify)"
            )
        return flyback_point(
            vin=params[sc],
            vout=params["vout"],
            iout=params["iout_max"],
            fsw=params["fsw"],
            lp=params.get("lp", 0.0),
            n=n,
            eta=eta,
            vf=vf,
            v_spike=spike,
        )

    def compute(self, params: Mapping[str, float]) -> dict[str, list[StressSpec]]:
        return self.compute_full(params).stress

    def compute_full(self, params: Mapping[str, float]) -> TemplateOutput:
        out = TemplateOutput()
        missing = [k for k in ("n", "lp") if k not in params]
        out.needs.extend(missing)
        out.diagnostics = self.validity_checks(params)
        if any(d.severity is Severity.ERROR for d in out.diagnostics):
            return out
        if "vd" not in params:
            out.needs.append("vd")
        band = float(load_defaults()["boundary_band"])
        notes: dict[str, str] = {}
        for sc in SCENARIOS:
            p = self._point(params, sc, notes)
            self._emit(out, p, sc, params, notes)
            if abs(p.boundary_margin) <= band:
                out.diagnostics.append(
                    _diag(
                        "TEMPLATE_NEAR_BOUNDARY",
                        f"{sc}: {p.mode.upper()} within {band:.0%} of the CCM/DCM boundary "
                        f"(margin {p.boundary_margin:.2f})",
                    )
                )
        out.diagnostics += [_diag("TEMPLATE_ASSUMED", text) for text in notes.values()]
        return out

    def _emit(
        self,
        out: TemplateOutput,
        p: FlybackPoint,
        sc: str,
        params: Mapping[str, float],
        notes: dict[str, str],
    ) -> None:
        mode = f"{p.mode.upper()}, D={p.duty:.3f}"
        spike_note = notes.get("v_spike", "Vspike from clamp rating")
        for role in ("primary_switch", "ic"):
            out.add(role, _s("i_rms", p.i_pri_rms, "A", Stat.RMS, sc, mode))
            out.add(role, _s("i_peak", p.i_pri_peak, "A", Stat.PEAK, sc, mode))
            out.add(role, _s("v_peak", p.v_ds_max, "V", Stat.PEAK, sc, spike_note))
        if "rds_pri" in params:
            loss = p.i_pri_rms**2 * params["rds_pri"]
            out.add("primary_switch", _s("p_loss", loss, "W", Stat.AVG, sc, "conduction at 25 C"))
        out.add("transformer", _s("i_rms_pri", p.i_pri_rms, "A", Stat.RMS, sc, mode))
        out.add("transformer", _s("i_rms_sec", p.i_sec_rms, "A", Stat.RMS, sc, mode))
        out.add("transformer", _s("i_peak", p.i_pri_peak, "A", Stat.PEAK, sc, "primary"))
        out.add("output_diode", _s("i_avg", p.iout, "A", Stat.AVG, sc))
        out.add("output_diode", _s("i_rms", p.i_sec_rms, "A", Stat.RMS, sc, mode))
        out.add("output_diode", _s("i_peak", p.i_sec_peak, "A", Stat.PEAK, sc, mode))
        out.add(
            "output_diode",
            _s("v_peak", p.v_diode_piv, "V", Stat.PEAK, sc, "ideal PIV; ringing not included (F4)"),
        )
        eta_note = notes.get("eta", "eta from rating")
        cap = "split equally among {} caps"
        out.add("output_cap", _s("i_rms", p.i_cout_rms, "A", Stat.RMS, sc, cap.format("output")))
        out.add("output_cap", _s("v_dc", p.vout, "V", Stat.DC, sc))
        out.add(
            "input_cap",
            _s("i_rms", p.i_cin_rms, "A", Stat.RMS, sc, f"{cap.format('input')}; {eta_note}"),
        )
        out.add("input_cap", _s("v_dc", p.vin, "V", Stat.DC, sc))


def _s(  # noqa: PLR0917 - mirrors StressSpec field order
    param: str, value: float, unit: str, stat: Stat, scenario: str, note: str | None = None
) -> StressSpec:
    return StressSpec(param=param, value=value, unit=unit, stat=stat, scenario=scenario, note=note)


def _diag(code: str, message: str, error: bool = False) -> Diagnostic:
    sev = Severity.ERROR if error else Severity.WARNING
    return Diagnostic(code=code, severity=sev, message=message, module=MODULE)
