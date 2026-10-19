"""Buck converter Tier 1 equations: ideal steady-state CCM (PRD section 3.2, "Buck (CCM)").

Shared by the ``buck`` (discrete) and ``buck_integrated`` templates. Pure functions; every
symbol in SI units. Hand-calculated reference: PRD section 8.2, Design A.

    D        = Vout / Vin                       (diode version: (Vout+Vd)/(Vin+Vd))
    DIL      = Vout * (1 - D) / (L * fsw)
    IL_pk    = Iout + DIL/2        IL_valley = Iout - DIL/2
    IL_rms   = sqrt(Iout^2 + DIL^2/12)
    CCM edge : Iout > DIL/2   (else DCM -> flag)
    HS FET   : Irms_HS = sqrt(D * (Iout^2 + DIL^2/12)),  Vds_max = Vin
    LS/diode : Irms_LS = sqrt((1-D) * (Iout^2 + DIL^2/12)),  Id_avg = Iout*(1-D)
    Cin      : Icin_rms = Iout * sqrt(D*(1-D))      (ideal source, DIL << Iout)
    Cout     : Icout_rms = DIL / (2*sqrt(3))        (triangular)
    dVout    = DIL/(8*fsw*Cout) + DIL*ESR
    P_cu     = IL_rms^2 * DCR
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DCM_BOUNDARY_BAND = 0.20  # F5: flag when Iout is within +-20 % of the CCM/DCM edge (PRD 3.3)


class BuckInputError(ValueError):
    """Invalid operating point (OPC-04): D >= 1, non-positive L*fsw, negative values."""


@dataclass(frozen=True)
class BuckPoint:
    """All Tier 1 quantities at one operating point."""

    vin: float
    vout: float
    iout: float
    fsw: float
    inductance: float
    duty: float
    ripple_pp: float  # DIL
    il_peak: float
    il_valley: float
    il_rms: float
    i_hs_rms: float
    i_ls_rms: float
    i_ls_avg: float
    v_sw_max: float  # Vds_max on both switches = Vin (ideal)
    i_cin_rms: float
    i_cout_rms: float
    v_out_ripple: float | None  # None when Cout unknown
    p_inductor_cu: float | None  # None when DCR unknown
    ccm: bool
    near_boundary: bool  # within DCM_BOUNDARY_BAND of the CCM/DCM edge

    @property
    def boundary_margin(self) -> float:
        """(Iout - DIL/2) / Iout: 0 at the CCM/DCM edge, 1 for pure DC."""
        return (self.iout - self.ripple_pp / 2) / self.iout if self.iout else 0.0


def buck_point(
    *,
    vin: float,
    vout: float,
    iout: float,
    fsw: float,
    inductance: float,
    cout: float | None = None,
    esr: float | None = None,
    dcr: float | None = None,
    diode_drop: float | None = None,
) -> BuckPoint:
    """Evaluate the buck at one (Vin, Iout). ``diode_drop`` switches to the asynchronous form."""
    for name, val in (
        ("vin", vin),
        ("vout", vout),
        ("iout", iout),
        ("fsw", fsw),
        ("L", inductance),
    ):
        if not math.isfinite(val) or val <= 0:
            msg = f"{name} must be a positive finite number, got {val!r}"
            raise BuckInputError(msg)
    duty = vout / vin if diode_drop is None else (vout + diode_drop) / (vin + diode_drop)
    if duty >= 1.0:
        msg = f"duty {duty:.3f} >= 1: Vout {vout} V cannot be reached from Vin {vin} V"
        raise BuckInputError(msg)
    lf = inductance * fsw
    if lf <= 0:
        msg = "L * fsw must be positive"
        raise BuckInputError(msg)

    ripple = vout * (1.0 - duty) / lf
    ac_term = iout**2 + ripple**2 / 12.0
    half = ripple / 2.0
    edge_margin = (iout - half) / iout
    return BuckPoint(
        vin=vin,
        vout=vout,
        iout=iout,
        fsw=fsw,
        inductance=inductance,
        duty=duty,
        ripple_pp=ripple,
        il_peak=iout + half,
        il_valley=iout - half,
        il_rms=math.sqrt(ac_term),
        i_hs_rms=math.sqrt(duty * ac_term),
        i_ls_rms=math.sqrt((1.0 - duty) * ac_term),
        i_ls_avg=iout * (1.0 - duty),
        v_sw_max=vin,
        i_cin_rms=iout * math.sqrt(duty * (1.0 - duty)),
        i_cout_rms=ripple / (2.0 * math.sqrt(3.0)),
        v_out_ripple=(ripple / (8.0 * fsw * cout) + ripple * (esr or 0.0)) if cout else None,
        p_inductor_cu=(ac_term * dcr) if dcr is not None else None,
        ccm=iout > half,
        near_boundary=abs(edge_margin) <= DCM_BOUNDARY_BAND,
    )
