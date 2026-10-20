"""Triage flags and ranking (PRD 3.3, TRI-01..06).

    score = w1 * clamp(1 - margin/margin_thr, 0, 1)                 F1 low margin
          + w2 * clamp(1 - (Tjmax - Tj)/tj_thr, 0, 1)                F2 thermal proximity
          + w3 * clamp(1 - life/target, 0, 1)                        F3 (needs M7; not scored yet)
          + w4 * blind_spot_weight                                   F4 closed-form blind spot
F0 (rating missing, status UNKNOWN) adds w1 * no_data so missing data is never a pass (TRI-05).
A flag whose stress is already Tier 2 is "refined" and not raised again (TRI-04). Waived
(part, flag) pairs keep their item with status ``waived`` and the reason (TRI-03).
Each F4 flag yields one ValuePrompt (origin M3), de-duplicated against prompts already open.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dfr.core.contracts import (
    DeratingResult,
    DeratingStatus,
    Part,
    PromptOrigin,
    RefinementItem,
    RoleMap,
    StressKey,
    StressValue,
    ThermalResult,
    Tier,
    ValuePrompt,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.modules.m3_triage.config import MODULE_ID, BlindSpot, TriageConfig

PromptKey = tuple[int | None, str, str]


@dataclass(frozen=True)
class Waiver:
    part_id: int
    flag: str  # "F1", "F2", "F4:<blind_spot_id>", ...
    reason: str


@dataclass
class _Acc:
    flags: list[str]
    reasons: list[str]
    score: float = 0.0
    params: list[str] | None = None
    scenarios: list[str] | None = None
    prompts: list[ValuePrompt] | None = None
    waived: list[str] | None = None


def clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def triage(
    parts: list[Part],
    derating: list[DeratingResult],
    cfg: TriageConfig,
    *,
    effective: Mapping[StressKey, StressValue] | None = None,
    thermal: list[ThermalResult] | None = None,
    topology: str | None = None,
    roles: RoleMap | None = None,
    existing_prompts: Iterable[ValuePrompt] = (),
    waivers: Iterable[Waiver] = (),
    sink: DiagnosticSink | None = None,
) -> list[RefinementItem]:
    sink = sink if sink is not None else DiagnosticSink(MODULE_ID)
    by_id = {v.id: v for v in (effective or {}).values() if v.id is not None}
    t2_keys = {k for k, v in (effective or {}).items() if v.tier is Tier.T2}
    waived = {(w.part_id, w.flag): w.reason for w in waivers}
    seen_prompts: set[PromptKey] = {(p.part_id, p.param, p.scenario) for p in existing_prompts}
    tj_by_part: dict[int, ThermalResult] = {}
    for t in thermal or []:
        cur = tj_by_part.get(t.part_id)
        if cur is None or t.tj > cur.tj:
            tj_by_part[t.part_id] = t

    items: list[RefinementItem] = []
    for part in parts:
        if part.id is None or part.dnp:
            continue
        acc = _Acc([], [], 0.0, [], [], [], [])
        rows = [r for r in derating if r.part_id == part.id]
        for r in sorted(rows, key=lambda r: r.margin if r.margin is not None else -9.0):
            _flag_margin(part, r, cfg, by_id, t2_keys, waived, acc, sink)
        worst_tj = tj_by_part.get(part.id)
        if worst_tj is not None:
            _flag_thermal(part, worst_tj, cfg, waived, acc)
        if roles is not None and topology is not None:
            part_roles = {role for role, refs in roles.roles.items() if part.refdes in refs}
            for spot in cfg.spots_for(topology, part_roles):
                _flag_blind_spot(part, spot, cfg, t2_keys, seen_prompts, waived, acc, sink)
        if not acc.flags and not acc.waived:
            continue
        status = "open" if acc.flags else "waived"
        items.append(
            RefinementItem(
                part_id=part.id,
                flags=[*acc.flags, *(acc.waived or [])],
                reasons=acc.reasons,
                score=round(acc.score, 4),
                parameters_to_refine=list(dict.fromkeys(acc.params or [])),
                recommended_scenarios=list(dict.fromkeys(acc.scenarios or [])),
                prompts=acc.prompts or [],
                status=status,
                waiver_reason="; ".join(
                    waived[(part.id, f)] for f in (acc.waived or []) if (part.id, f) in waived
                )
                or None,
            )
        )
    items.sort(key=lambda i: (i.status != "open", -i.score, i.part_id))
    sink.info(
        "TRIAGE_SUMMARY",
        f"{sum(i.status == 'open' for i in items)} open, "
        f"{sum(i.status == 'waived' for i in items)} waived, "
        f"{sum(len(i.prompts) for i in items)} prompts",
    )
    return items


# ----------------------------------------------------------------------------- flags


def _flag_margin(  # noqa: PLR0917
    part: Part,
    r: DeratingResult,
    cfg: TriageConfig,
    by_id: Mapping[int, StressValue],
    t2_keys: set[StressKey],
    waived: Mapping[tuple[int, str], str],
    acc: _Acc,
    sink: DiagnosticSink,
) -> None:
    pid = part.id or 0
    used = [by_id[i] for i in r.stress_value_ids if i in by_id]
    scenarios = [v.scenario for v in used]
    if r.status is DeratingStatus.UNKNOWN:
        flag = "F0"
        reason = (
            f"{part.refdes}: {r.param} has no rating for rule {r.rule_id}; status UNKNOWN "
            "(add the rating in the part catalog)"
        )
        if (pid, flag) in waived:
            _waive(acc, flag)
            return
        _add(acc, flag, reason, cfg.w1_margin * cfg.no_data)
        return
    if r.margin is None or r.margin >= cfg.margin_threshold:
        return
    flag = "F1"
    if any(v.key in t2_keys for v in used):
        sink.info(
            "TRIAGE_ALREADY_REFINED",
            f"{part.refdes}: {r.param} already has a Tier 2 value; F1 not re-flagged",
            part_id=pid,
        )
        return
    ratio_txt = f"{r.ratio * 100:.0f} % of derated limit" if r.ratio is not None else "over limit"
    reason = (
        f"{part.refdes}: {r.param} {ratio_txt}; margin {r.margin * 100:.0f} % "
        f"< {cfg.margin_threshold * 100:.0f} % ({r.status.value.upper()}, {r.rule_id})"
    )
    if (pid, flag) in waived:
        _waive(acc, flag)
        return
    _add(acc, flag, reason, cfg.w1_margin * clamp01(1.0 - r.margin / cfg.margin_threshold))
    assert acc.params is not None and acc.scenarios is not None
    acc.params.append(r.param)
    acc.scenarios.extend(scenarios)


def _flag_thermal(
    part: Part,
    t: ThermalResult,
    cfg: TriageConfig,
    waived: Mapping[tuple[int, str], str],
    acc: _Acc,
) -> None:
    pid = part.id or 0
    tj_max = part.ratings.get("tj_max")
    if tj_max is None:
        if (pid, "F0") in waived:
            _waive(acc, "F0")
        else:
            _add(
                acc,
                "F0",
                f"{part.refdes}: Tj {t.tj:.0f} degC computed but no tj_max rating",
                cfg.w1_margin * cfg.no_data,
            )
        return
    headroom = tj_max.value - t.tj
    if headroom >= cfg.tj_proximity_c:
        return
    if (pid, "F2") in waived:
        _waive(acc, "F2")
        return
    _add(
        acc,
        "F2",
        f"{part.refdes}: Tj {t.tj:.0f} degC within {headroom:.0f} degC of Tjmax "
        f"{tj_max.value:.0f} degC (< {cfg.tj_proximity_c:.0f} degC) [{t.scenario}]",
        cfg.w2_thermal * clamp01(1.0 - headroom / cfg.tj_proximity_c),
    )
    assert acc.params is not None and acc.scenarios is not None
    acc.params.append("p_loss")
    acc.scenarios.append(t.scenario)


def _flag_blind_spot(  # noqa: PLR0917
    part: Part,
    spot: BlindSpot,
    cfg: TriageConfig,
    t2_keys: set[StressKey],
    seen_prompts: set[PromptKey],
    waived: Mapping[tuple[int, str], str],
    acc: _Acc,
    sink: DiagnosticSink,
) -> None:
    pid = part.id or 0
    flag = f"F4:{spot.id}"
    if StressKey(pid, spot.param, spot.scenario) in t2_keys:
        sink.info(
            "TRIAGE_ALREADY_REFINED",
            f"{part.refdes}: {spot.param} [{spot.scenario}] has a Tier 2 value; {flag} closed",
            part_id=pid,
        )
        return
    if (pid, flag) in waived:
        _waive(acc, flag)
        return
    _add(acc, flag, f"{part.refdes}: {spot.reason}", cfg.w4_blind_spot * spot.weight)
    assert acc.params is not None and acc.scenarios is not None and acc.prompts is not None
    acc.params.append(spot.param)
    acc.scenarios.append(spot.scenario)
    key: PromptKey = (pid, spot.param, spot.scenario)
    if key in seen_prompts:
        return
    seen_prompts.add(key)
    acc.prompts.append(
        ValuePrompt(
            part_id=pid,
            param=spot.param,
            stat=spot.stat,
            scenario=spot.scenario,
            reason=f"{spot.reason} ({spot.source})",
            how_to_obtain=spot.how,
            origin=PromptOrigin.M3,
        )
    )


def _add(acc: _Acc, flag: str, reason: str, score: float) -> None:
    if flag not in acc.flags:
        acc.flags.append(flag)
    acc.reasons.append(reason)
    acc.score += score


def _waive(acc: _Acc, flag: str) -> None:
    assert acc.waived is not None
    if flag not in acc.waived:
        acc.waived.append(flag)
