"""Boost and inverting buck-boost Tier 1 equations: ideal steady-state CCM (PRD section 3.2,
"Boost (CCM)" and "Buck-boost (inverting, CCM)"). Pure functions, SI units.

Boost (Vf = rectifier forward drop, 0 for a synchronous rectifier):
    D        = 1 - Vin / (Vout + Vf)            (PRD form 1 - Vin/Vout when Vf = 0)
    IL_avg   = Iout / (1 - D)
    DIL      = Vin * D / (L * fsw)
    IL_pk    = IL_avg + DIL/2          IL_rms = sqrt(IL_avg^2 + DIL^2/12)
    Switch   : Irms_Q = sqrt(D * (IL_avg^2 + DIL^2/12)),       Vds_max = Vout + Vf
    Diode    : Iavg_D = Iout,  Irms_D = sqrt((1-D) * (IL_avg^2 + DIL^2/12)),  VR_max = Vout
    Cout     : Icout_rms = sqrt(Irms_D^2 - Iout^2)
    Cin      : Icin_rms  = DIL / (2*sqrt(3))       (inductor in series with the source)
    dVout    = Iout*D/(fsw*Cout) + ESR*IL_pk
    CCM edge : IL_avg > DIL/2

Inverting buck-boost (|Vout| = magnitude of the negative output):
    D        = (|Vout| + Vf) / (Vin + |Vout| + Vf)
    IL_avg   = Iout / (1 - D),  DIL = Vin * D / (L * fsw)
    Switch/diode RMS: same form as boost;  Vds_max = VR_max = Vin + |Vout| (+ Vf on the switch)
    Cout     : Icout_rms = sqrt(Irms_D^2 - Iout^2)
    Cin      : Icin_rms  = sqrt(Irms_Q^2 - (D*IL_avg)^2)
    dVout    = Iout*D/(fsw*Cout) + ESR*IL_pk
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DCM_BOUNDARY_BAND = 0.20  # F5: flag within +-20 % of the CCM/DCM edge (PRD 3.3, verify)


class BoostInputError(ValueError):
    """Invalid operating point (OPC-04): D outside (0, 1), non-positive inputs."""


@dataclass(frozen=True)
class BoostPoint:
    """All Tier 1 quantities at one operating point (boost or inverting buck-boost)."""

    vin: float
    vout: float  # magnitude
    iout: float
    fsw: float
    inductance: float
    duty: float
    il_avg: float
    ripple_pp: float
    il_peak: float
    il_rms: float
    i_sw_rms: float
    i_d_avg: float
    i_d_rms: float
    v_sw_max: float  # switch Vds_max
    v_d_max: float  # rectifier reverse voltage
    i_cin_rms: float
    i_cout_rms: float
    v_out_ripple: float | None
    p_inductor_cu: float | None
    ccm: bool
    near_boundary: bool

    @property
    def boundary_margin(self) -> float:
        """(IL_avg - DIL/2) / IL_avg: 0 at the CCM/DCM edge."""
        return (self.il_avg - self.ripple_pp / 2) / self.il_avg


def _check(**vals: float) -> None:
    for name, val in vals.items():
        if not math.isfinite(val) or val <= 0:
            msg = f"{name} must be a positive finite number, got {val!r}"
            raise BoostInputError(msg)


def _point(
    *,
    inverting: bool,
    vin: float,
    vout: float,
    iout: float,
    fsw: float,
    inductance: float,
    cout: float | None,
    esr: float | None,
    dcr: float | None,
    vf: float,
) -> BoostPoint:
    vout = abs(vout)
    _check(vin=vin, vout=vout, iout=iout, fsw=fsw, L=inductance)
    if vf < 0:
        msg = f"diode drop must be >= 0, got {vf!r}"
        raise BoostInputError(msg)
    duty = (vout + vf) / (vin + vout + vf) if inverting else 1.0 - vin / (vout + vf)
    if not 0.0 < duty < 1.0:
        msg = f"duty {duty:.3f} outside (0, 1): boost needs Vout > Vin (Vin {vin} V, Vout {vout} V)"
        raise BoostInputError(msg)
    il_avg = iout / (1.0 - duty)
    ripple = vin * duty / (inductance * fsw)
    ac = il_avg**2 + ripple**2 / 12.0
    i_sw_rms = math.sqrt(duty * ac)
    i_d_rms = math.sqrt((1.0 - duty) * ac)
    il_peak = il_avg + ripple / 2.0
    i_cin = (
        math.sqrt(max(i_sw_rms**2 - (duty * il_avg) ** 2, 0.0))
        if inverting
        else ripple / (2.0 * math.sqrt(3.0))
    )
    v_block = vin + vout if inverting else vout
    margin = (il_avg - ripple / 2.0) / il_avg
    return BoostPoint(
        vin=vin,
        vout=vout,
        iout=iout,
        fsw=fsw,
        inductance=inductance,
        duty=duty,
        il_avg=il_avg,
        ripple_pp=ripple,
        il_peak=il_peak,
        il_rms=math.sqrt(ac),
        i_sw_rms=i_sw_rms,
        i_d_avg=iout,
        i_d_rms=i_d_rms,
        v_sw_max=v_block + vf,
        v_d_max=v_block,
        i_cin_rms=i_cin,
        i_cout_rms=math.sqrt(max(i_d_rms**2 - iout**2, 0.0)),
        v_out_ripple=(iout * duty / (fsw * cout) + (esr or 0.0) * il_peak) if cout else None,
        p_inductor_cu=ac * dcr if dcr is not None else None,
        ccm=il_avg > ripple / 2.0,
        near_boundary=abs(margin) <= DCM_BOUNDARY_BAND,
    )


def boost_point(
    *,
    vin: float,
    vout: float,
    iout: float,
    fsw: float,
    inductance: float,
    cout: float | None = None,
    esr: float | None = None,
    dcr: float | None = None,
    vf: float = 0.0,
) -> BoostPoint:
    """Boost at one (Vin, Iout). PRD 3.2 "Boost (CCM)"."""
    return _point(
        inverting=False,
        vin=vin,
        vout=vout,
        iout=iout,
        fsw=fsw,
        inductance=inductance,
        cout=cout,
        esr=esr,
        dcr=dcr,
        vf=vf,
    )


def buck_boost_point(
    *,
    vin: float,
    vout: float,
    iout: float,
    fsw: float,
    inductance: float,
    cout: float | None = None,
    esr: float | None = None,
    dcr: float | None = None,
    vf: float = 0.0,
) -> BoostPoint:
    """Inverting buck-boost at one (Vin, Iout); ``vout`` sign ignored. PRD 3.2."""
    return _point(
        inverting=True,
        vin=vin,
        vout=vout,
        iout=iout,
        fsw=fsw,
        inductance=inductance,
        cout=cout,
        esr=esr,
        dcr=dcr,
        vf=vf,
    )
