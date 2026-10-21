"""Flyback Tier 1 equations, CCM and DCM with automatic mode selection (PRD section 3.2,
"Flyback"; T27). Pure functions, SI units.

    n = Np/Ns,  Pin = Pout/eta,  Pout = Vout*Iout,  Vf = output diode drop,  Ls = Lp/n^2
    Vreflected = n * (Vout + Vf)
    CCM : D = Vreflected / (Vin + Vreflected)
          Iavg_pri = Pin / (Vin * D);  DI = Vin*D/(Lp*fsw);  Ipk = Iavg_pri + DI/2
          Irms_pri = sqrt(D * (Iavg_pri^2 + DI^2/12))
          secondary (load side): Isec_avg_on = Iout/(1-D),  DIs = n*DI
          Irms_sec = sqrt((1-D) * (Isec_avg_on^2 + DIs^2/12)),  Ipk_sec = Isec_avg_on + DIs/2
    DCM : Ipk = sqrt(2*Pin/(Lp*fsw));  D = Lp*Ipk*fsw/Vin;  Irms_pri = Ipk*sqrt(D/3)
          Ipk_sec = n*Ipk;  D2 = Ls*Ipk_sec*fsw/(Vout+Vf);  Irms_sec = Ipk_sec*sqrt(D2/3)
    Mode: CCM while the CCM valley Iavg_pri - DI/2 > 0, else DCM (D + D2 < 1).
          Boundary margin: CCM (Iavg_pri - DI/2)/Iavg_pri; DCM 1 - (D + D2).
    Vds_max = Vin + Vreflected + Vspike;   Diode PIV = Vout + Vin/n
    Cin  : Icin_rms  = sqrt(Irms_pri^2 - Iin^2),  Iin = Pin/Vin
    Cout : Icout_rms = sqrt(Irms_sec^2 - Iout^2)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class FlybackInputError(ValueError):
    """Invalid operating point (OPC-04)."""


@dataclass(frozen=True)
class FlybackPoint:
    vin: float
    vout: float
    iout: float
    mode: str  # "ccm" | "dcm"
    duty: float
    duty_off: float  # D2 in DCM, 1 - D in CCM
    v_reflected: float
    i_pri_peak: float
    i_pri_rms: float
    i_sec_peak: float
    i_sec_rms: float
    i_in_avg: float
    v_ds_max: float
    v_diode_piv: float
    i_cin_rms: float
    i_cout_rms: float
    boundary_margin: float


def flyback_point(
    *,
    vin: float,
    vout: float,
    iout: float,
    fsw: float,
    lp: float,
    n: float,
    eta: float,
    vf: float = 0.0,
    v_spike: float = 0.0,
) -> FlybackPoint:
    for name, val in (("vin", vin), ("vout", vout), ("iout", iout), ("fsw", fsw), ("Lp", lp)):
        if not math.isfinite(val) or val <= 0:
            msg = f"{name} must be a positive finite number, got {val!r}"
            raise FlybackInputError(msg)
    if not n > 0 or not 0 < eta <= 1 or vf < 0 or v_spike < 0:
        msg = f"need n > 0, 0 < eta <= 1, Vf >= 0, Vspike >= 0 (n={n}, eta={eta})"
        raise FlybackInputError(msg)
    p_in = vout * iout / eta
    v_ref = n * (vout + vf)
    d = v_ref / (vin + v_ref)
    i_avg_pri = p_in / (vin * d)
    di = vin * d / (lp * fsw)
    if i_avg_pri - di / 2 > 0:  # CCM
        mode, d2 = "ccm", 1.0 - d
        i_pk = i_avg_pri + di / 2
        i_rms_pri = math.sqrt(d * (i_avg_pri**2 + di**2 / 12))
        i_sec_on = iout / (1.0 - d)
        dis = n * di
        i_pk_sec = i_sec_on + dis / 2
        i_rms_sec = math.sqrt((1.0 - d) * (i_sec_on**2 + dis**2 / 12))
        margin = (i_avg_pri - di / 2) / i_avg_pri
    else:  # DCM
        mode = "dcm"
        i_pk = math.sqrt(2 * p_in / (lp * fsw))
        d = lp * i_pk * fsw / vin
        i_rms_pri = i_pk * math.sqrt(d / 3)
        i_pk_sec = n * i_pk
        d2 = (lp / n**2) * i_pk_sec * fsw / (vout + vf)
        i_rms_sec = i_pk_sec * math.sqrt(d2 / 3)
        margin = 1.0 - (d + d2)
    i_in = p_in / vin
    return FlybackPoint(
        vin=vin,
        vout=vout,
        iout=iout,
        mode=mode,
        duty=d,
        duty_off=d2,
        v_reflected=v_ref,
        i_pri_peak=i_pk,
        i_pri_rms=i_rms_pri,
        i_sec_peak=i_pk_sec,
        i_sec_rms=i_rms_sec,
        i_in_avg=i_in,
        v_ds_max=vin + v_ref + v_spike,
        v_diode_piv=vout + vin / n,
        i_cin_rms=math.sqrt(max(i_rms_pri**2 - i_in**2, 0.0)),
        i_cout_rms=math.sqrt(max(i_rms_sec**2 - iout**2, 0.0)),
        boundary_margin=margin,
    )
