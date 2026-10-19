"""Semiconductor and magnetic loss terms shared by all templates (PRD 3.2, "Loss terms").

    Rds_on(Tj) = Rds_on_25 * (1 + alpha * (Tj - 25))   alpha ~ 0.004-0.007 /degC (verify)
    P_cond     = Irms^2 * Rds_on(Tj)
    P_sw       = 0.5 * Vds * Id * (tr + tf) * fsw        (hard-switched overlap, approximate)
    P_coss     = 0.5 * Coss_eq * Vds^2 * fsw             (or Eoss * fsw)
    P_gate     = Qg * Vgs * fsw
    P_rr       = Qrr * Vds * fsw
    P_deadtime = Vsd * Iout * (t_dr + t_df) * fsw
    Diode      : P_d = Vf * Iavg + Rd * Irms^2  (+ P_rr for non-Schottky)
    Inductor core (optional): Pv = k * f^a * B^b  (Steinmetz; user supplies k, a, b)

All inputs SI. Functions return None when a required datum is missing so callers emit a
ValuePrompt instead of guessing (PRD 3.2 mode d).
"""

from __future__ import annotations

from dataclasses import dataclass

RDS_ON_ALPHA_DEFAULT = 0.005  # /degC, midpoint of PRD range; verify against datasheet curve
T_REF_C = 25.0


def rds_on_at(rds_on_25: float, tj_c: float, alpha: float = RDS_ON_ALPHA_DEFAULT) -> float:
    return rds_on_25 * (1.0 + alpha * (tj_c - T_REF_C))


def p_conduction(i_rms: float, rds_on: float) -> float:
    return i_rms**2 * rds_on


def p_switching(vds: float, i_d: float, t_rise: float, t_fall: float, fsw: float) -> float:
    return 0.5 * vds * i_d * (t_rise + t_fall) * fsw


def p_coss(
    vds: float, fsw: float, *, coss_eq: float | None = None, eoss: float | None = None
) -> float | None:
    if eoss is not None:
        return eoss * fsw
    if coss_eq is not None:
        return 0.5 * coss_eq * vds**2 * fsw
    return None


def p_gate(qg: float, vgs: float, fsw: float) -> float:
    return qg * vgs * fsw


def p_reverse_recovery(qrr: float, vds: float, fsw: float) -> float:
    return qrr * vds * fsw


def p_deadtime(
    vsd: float, iout: float, t_dead_rise: float, t_dead_fall: float, fsw: float
) -> float:
    return vsd * iout * (t_dead_rise + t_dead_fall) * fsw


def p_diode(vf: float, i_avg: float, i_rms: float, rd: float = 0.0, p_rr: float = 0.0) -> float:
    return vf * i_avg + rd * i_rms**2 + p_rr


def p_inductor_copper(i_rms: float, dcr: float) -> float:
    return i_rms**2 * dcr


def p_steinmetz(  # noqa: PLR0917 - Steinmetz symbols in conventional order
    k: float, f: float, b_peak: float, a: float, b: float, volume: float = 1.0
) -> float:
    """Core loss density k*f^a*B^b times core volume (user-supplied constants)."""
    return float(k * f**a * b_peak**b * volume)


@dataclass(frozen=True)
class MosfetLoss:
    p_cond: float
    p_sw: float | None
    p_coss: float | None
    p_gate: float | None
    p_rr: float | None
    missing: tuple[str, ...]

    @property
    def total(self) -> float:
        return sum(x for x in (self.p_cond, self.p_sw, self.p_coss, self.p_gate, self.p_rr) if x)


def mosfet_loss(
    *,
    i_rms: float,
    rds_on_25: float,
    tj_c: float,
    vds: float,
    i_switch: float,
    fsw: float,
    t_rise: float | None = None,
    t_fall: float | None = None,
    qg: float | None = None,
    vgs: float | None = None,
    qrr: float | None = None,
    coss_eq: float | None = None,
    eoss: float | None = None,
    alpha: float = RDS_ON_ALPHA_DEFAULT,
    hard_switched: bool = True,
) -> MosfetLoss:
    """Conduction always; each other term only when its data exists, else listed in ``missing``."""
    missing: list[str] = []
    p_cond = p_conduction(i_rms, rds_on_at(rds_on_25, tj_c, alpha))
    p_sw: float | None = None
    if hard_switched:
        if t_rise is not None and t_fall is not None:
            p_sw = p_switching(vds, i_switch, t_rise, t_fall, fsw)
        else:
            missing.append("t_rise/t_fall")
    p_c = p_coss(vds, fsw, coss_eq=coss_eq, eoss=eoss)
    if p_c is None:
        missing.append("coss_eq/eoss")
    p_g = p_gate(qg, vgs, fsw) if (qg is not None and vgs is not None) else None
    if p_g is None:
        missing.append("qg/vgs")
    p_r = p_reverse_recovery(qrr, vds, fsw) if qrr is not None else None
    return MosfetLoss(p_cond, p_sw, p_c, p_g, p_r, tuple(missing))
