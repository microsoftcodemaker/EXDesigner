"""LifetimeModel implementations (PRD 3.7, LIF-01..06).

Each model: ``applies_to(part)`` by class/subtype; ``estimate(part, stress, thermal, ctx)``
returns one ``LifetimeResult``. Missing vendor data -> ``life_hours=None`` with the reason in
``assumptions`` (LIF-06). Confidence is ``low`` whenever a seed constant from the data file
decided the number (PRD 3.7 "Output"). ``ctx`` is a :class:`LifetimeContext`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dfr.core.contracts import (
    Confidence,
    LifetimeResult,
    MissionProfile,
    Part,
    PartClass,
    StressValue,
    ThermalResult,
)
from dfr.core.extension import LifetimeModel
from dfr.modules.m7_lifetime.constants import HOURS_PER_YEAR, CapacitorRule, LifetimeConstants
from dfr.modules.m7_lifetime.equations import (
    connector_life_hours,
    core_temperature,
    miner_life_hours,
    prokopowicz_vaskas_life_hours,
    temperature_rule_life_hours,
)

VERSION = "0.1.0"


@dataclass(frozen=True)
class LifetimeContext:
    constants: LifetimeConstants
    profile: MissionProfile
    t_ambient: float


def _worst(stress: Sequence[StressValue], param: str) -> StressValue | None:
    rows = [s for s in stress if s.param == param]
    return max(rows, key=lambda s: s.value) if rows else None


def _rating(part: Part, name: str) -> float | None:
    r = part.ratings.get(name)
    return r.value if r is not None else None


def _na(part: Part, mechanism: str, model_id: str, why: str, *more: str) -> LifetimeResult:
    return LifetimeResult(
        part_id=part.id or 0,
        mechanism=mechanism,
        model_id=model_id,
        life_hours=None,
        confidence=Confidence.LOW,
        assumptions=(f"not available: {why}", *more),
    )


class CapacitorTemperatureRule(LifetimeModel):
    """Aluminium electrolytic (10-degree rule) and polymer (own exponent) capacitors (LIF-01).

    Ratings used: ``l0_hours``, ``t0_rated`` (required), ``i_ripple`` (required when a ripple
    current stress exists), ``dt0_core`` (optional; seed default otherwise -> low confidence).
    """

    def __init__(self, subtype: str, rule: CapacitorRule) -> None:
        self.subtype = subtype
        self.rule = rule
        self.id = f"cap_{subtype}_temperature_rule"
        self.version = VERSION
        self.mechanism = "electrolyte_dry_out" if subtype == "aluminum_electrolytic" else "wear_out"

    def applies_to(self, part: Part) -> bool:
        return part.part_class is PartClass.CAPACITOR and part.subtype == self.subtype

    def estimate(
        self,
        part: Part,
        stress: Sequence[StressValue],
        thermal: ThermalResult | None,
        profile: object,
    ) -> LifetimeResult:
        del thermal
        assert isinstance(profile, LifetimeContext)
        l0, t0 = _rating(part, "l0_hours"), _rating(part, "t0_rated")
        if l0 is None or t0 is None:
            return _na(part, self.mechanism, self.id, "ratings l0_hours and t0_rated needed")
        i_rms = _worst(stress, "i_rms")
        assumptions = [f"{self.rule.source}; EOL {self.rule.end_of_life or 'per series'}"]
        confidence = Confidence.HIGH
        dt_core = 0.0
        ids: tuple[int, ...] = ()
        if i_rms is not None:
            i_rated = _rating(part, "i_ripple")
            if i_rated is None or i_rated <= 0:
                return _na(
                    part, self.mechanism, self.id, "rating i_ripple needed to scale the core rise"
                )
            dt0 = _rating(part, "dt0_core")
            if dt0 is None:
                dt0 = self.rule.default_dt0_core_k
                confidence = Confidence.LOW
                assumptions.append(f"dT0 core rise {dt0:g} K is a seed default (verify)")
            dt_core = core_temperature(0.0, dt0, i_rms.value, i_rated)
            assumptions.append(
                f"ripple {i_rms.value:.3g} A [{i_rms.scenario}] vs rated {i_rated:g} A; "
                "k(f) = 1 (no frequency multiplier table)"
            )
            if i_rms.id is not None:
                ids = (i_rms.id,)
        else:
            assumptions.append("no ripple current stress: core rise 0 K")
        t_core = profile.t_ambient + dt_core
        life = temperature_rule_life_hours(l0, t0, t_core, self.rule.degrees_per_doubling)
        if t_core > t0:
            assumptions.append(f"T_core {t_core:.0f} degC above T0 {t0:g} degC: extrapolated")
            confidence = Confidence.LOW
        cap = self.rule.life_cap_years * HOURS_PER_YEAR
        if life > cap:
            assumptions.append(f"capped at {self.rule.life_cap_years:g} years")
            life = cap
        assumptions.append(
            f"T_core {t_core:.1f} degC, {self.rule.degrees_per_doubling:g}-degree rule"
        )
        return LifetimeResult(
            part_id=part.id or 0,
            mechanism=self.mechanism,
            model_id=self.id,
            life_hours=life,
            confidence=min(confidence, self.rule.confidence, key=_conf_rank),
            assumptions=tuple(assumptions),
            input_stress_ids=ids,
        )


class MlccVoltageTemperature(LifetimeModel):
    """MLCC Prokopowicz-Vaskas acceleration from a vendor qualification point (LIF-02).

    Ratings: ``l1_hours``, ``v1_test``, ``t1_test`` (qualification point, required). Stress:
    worst ``v_dc``. n and Ea per dielectric come from the constants file (low confidence).
    """

    id = "mlcc_prokopowicz_vaskas"
    version = VERSION
    mechanism = "dielectric_wear_out"

    def applies_to(self, part: Part) -> bool:
        return part.part_class is PartClass.CAPACITOR and part.subtype == "ceramic"

    def estimate(
        self,
        part: Part,
        stress: Sequence[StressValue],
        thermal: ThermalResult | None,
        profile: object,
    ) -> LifetimeResult:
        del thermal
        assert isinstance(profile, LifetimeContext)
        l1, v1, t1 = (_rating(part, k) for k in ("l1_hours", "v1_test", "t1_test"))
        if l1 is None or v1 is None or t1 is None:
            return _na(
                part,
                self.mechanism,
                self.id,
                "vendor qualification point (l1_hours, v1_test, t1_test) needed",
            )
        v_dc = _worst(stress, "v_dc")
        if v_dc is None or v_dc.value <= 0:
            return _na(part, self.mechanism, self.id, "no DC voltage stress")
        c = profile.constants
        pv, key = c.mlcc(part.attributes.get("dielectric"))
        life = prokopowicz_vaskas_life_hours(
            l1, v1, t1, v_dc.value, profile.t_ambient, pv.n, pv.ea_ev, c.kb_ev_per_k
        )
        return LifetimeResult(
            part_id=part.id or 0,
            mechanism=self.mechanism,
            model_id=self.id,
            life_hours=life,
            confidence=c.mlcc_confidence,
            assumptions=(
                f"n = {pv.n:g}, Ea = {pv.ea_ev:g} eV for {key} ({c.mlcc_source})",
                f"qualification {l1:g} h at {v1:g} V / {t1:g} degC; field "
                f"{v_dc.value:.3g} V [{v_dc.scenario}] at Ta {profile.t_ambient:g} degC "
                "(self-heating ignored)",
            ),
            input_stress_ids=(v_dc.id,) if v_dc.id is not None else (),
        )


class ThermalCyclingMiner(LifetimeModel):
    """Die-attach / bond-wire fatigue: Coffin-Manson per bin, Miner's rule (LIF-03).

    Bins come from the thermal result's rainflow output when present; otherwise one power
    on/off cycle per ``MissionProfile.on_off_cycles_per_year`` with dTj = Tj - Ta_off.
    """

    id = "thermal_cycling_coffin_manson"
    version = VERSION
    mechanism = "thermal_cycling_fatigue"

    def applies_to(self, part: Part) -> bool:
        return part.part_class in (PartClass.TRANSISTOR, PartClass.DIODE, PartClass.IC)

    def estimate(
        self,
        part: Part,
        stress: Sequence[StressValue],
        thermal: ThermalResult | None,
        profile: object,
    ) -> LifetimeResult:
        del stress
        assert isinstance(profile, LifetimeContext)
        c = profile.constants
        cm = c.cycling_by_class.get(part.part_class.value)
        if cm is None:
            return _na(part, self.mechanism, self.id, f"no constants for {part.part_class.value}")
        if thermal is None:
            return _na(part, self.mechanism, self.id, "no junction temperature (M6 result)")
        assumptions = [f"A = {cm.a:g}, n = {cm.n:g} ({c.cycling_source})"]
        if thermal.delta_tj_cycles:
            bins = [(d, count) for d, _mean, count in thermal.delta_tj_cycles]
            assumptions.append(f"{len(bins)} rainflow bin(s) from the thermal result")
        else:
            ta_off = (
                profile.profile.t_ambient_off
                if profile.profile.t_ambient_off is not None
                else profile.t_ambient
            )
            bins = [(thermal.tj - ta_off, profile.profile.on_off_cycles_per_year)]
            assumptions.append(
                f"one on/off cycle dTj = {bins[0][0]:.1f} K x "
                f"{profile.profile.on_off_cycles_per_year:g}/year [{thermal.scenario}]"
            )
        life = miner_life_hours(bins, cm.a, cm.n, min_delta_tj=c.min_delta_tj_k)
        if life is None:
            assumptions.append(f"no swing >= {c.min_delta_tj_k:g} K: no cycling damage counted")
        return LifetimeResult(
            part_id=part.id or 0,
            mechanism=self.mechanism,
            model_id=self.id,
            life_hours=life,
            confidence=c.cycling_confidence,
            assumptions=tuple(assumptions),
            input_stress_ids=tuple(thermal.stress_value_ids),
        )


class ConnectorMating(LifetimeModel):
    """Connector mating-cycle life (LIF-04 connector part). Rating ``mating_cycles``."""

    id = "connector_mating_cycles"
    version = VERSION
    mechanism = "contact_wear"

    def applies_to(self, part: Part) -> bool:
        return part.part_class is PartClass.CONNECTOR

    def estimate(
        self,
        part: Part,
        stress: Sequence[StressValue],
        thermal: ThermalResult | None,
        profile: object,
    ) -> LifetimeResult:
        del stress, thermal
        assert isinstance(profile, LifetimeContext)
        rated = _rating(part, "mating_cycles")
        if rated is None or rated <= 0:
            return _na(part, self.mechanism, self.id, "rating mating_cycles needed")
        per_year = profile.profile.mating_cycles_per_year
        life = connector_life_hours(rated, per_year)
        why = (
            f"{rated:g} rated cycles / {per_year:g} per year"
            if life is not None
            else "mission profile has 0 mating cycles per year: no contact wear"
        )
        return LifetimeResult(
            part_id=part.id or 0,
            mechanism=self.mechanism,
            model_id=self.id,
            life_hours=life,
            confidence=profile.constants.connector_confidence,
            assumptions=(why, profile.constants.connector_source),
        )


def _conf_rank(c: Confidence) -> int:
    return {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}[c]


def default_models(constants: LifetimeConstants) -> list[LifetimeModel]:
    models: list[LifetimeModel] = []
    if constants.electrolytic is not None:
        models.append(CapacitorTemperatureRule("aluminum_electrolytic", constants.electrolytic))
    if constants.polymer is not None:
        models.append(CapacitorTemperatureRule("polymer", constants.polymer))
    models += [MlccVoltageTemperature(), ThermalCyclingMiner(), ConnectorMating()]
    return models
