"""M2 services: template stress, manual entry, prompts (PRD 3.2 modes a, b, d)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dfr.core.contracts import (
    ConverterSpec,
    Diagnostic,
    InferredValues,
    Part,
    PromptOrigin,
    RoleMap,
    Severity,
    Source,
    Stat,
    StressSpec,
    StressValue,
    Tier,
    ValuePrompt,
)
from dfr.core.diagnostics import DiagnosticSink
from dfr.core.extension import TopologyTemplate
from dfr.core.ports import Clock
from dfr.modules.m2_conditions.infer import MODULE_ID, infer_passives

# Stress rows that represent a total shared equally by parallel parts in the same role.
_SPLIT_PARAMS = {("output_cap", "i_rms"), ("input_cap", "i_rms")}
# Template `needs` -> prompt wording (tool-neutral, PRD 3.2 mode d).
_PROMPT_TEXT: dict[str, tuple[str, str, str, str]] = {
    # name: (param, stat, reason, how_to_obtain)
    "p_ic": (
        "p_loss",
        "avg",
        "IC loss cannot be computed: no internal Rds_on data and no efficiency",
        "read efficiency at Vin/Iout from the datasheet curve, or measure input and output power",
    ),
    "p_sw": (
        "p_loss",
        "avg",
        "switching loss of the integrated switches is not in the ratings",
        "datasheet switching-loss figure at fsw, or (Pin - Pout) minus conduction and "
        "inductor loss",
    ),
    "dcr": (
        "p_loss",
        "avg",
        "inductor DCR missing: copper loss not computed",
        "DCR from the inductor datasheet (typ. at 20 degC)",
    ),
    "vd": (
        "v_dc",
        "dc",
        "catch-diode forward drop missing (asynchronous buck)",
        "Vf at the output current from the diode datasheet",
    ),
}


@dataclass
class TemplateStress:
    stress: list[StressValue]
    prompts: list[ValuePrompt]
    inferred: InferredValues
    params: dict[str, float]
    diagnostics: list[Diagnostic] = field(default_factory=list)


def compute_template_stress(
    template: TopologyTemplate,
    spec: ConverterSpec,
    parts: list[Part],
    roles: RoleMap,
    clock: Clock,
    *,
    overrides: Mapping[str, float] | None = None,
    part_params: Mapping[str, float] | None = None,
) -> TemplateStress:
    """Tier 1 stress from the converter spec and confirmed roles (OPC-01, OPC-12, OPC-13)."""
    sink = DiagnosticSink(MODULE_ID)
    inferred = infer_passives(parts, roles, overrides=overrides, sink=sink)
    params: dict[str, float] = {
        "vin_min": spec.vin_min,
        "vin_max": spec.vin_max,
        "vout": spec.vout,
        "iout_max": spec.iout_max,
        "fsw": spec.fsw,
        "t_ambient": spec.t_ambient,
    }
    params.update({k: v.value for k, v in inferred.values.items()})
    params.update(_ic_params(parts, roles))
    params.update(_template_part_inputs(template, parts, roles, params))
    params.update(part_params or {})

    out = _template_output(template, params)
    sink.extend(out.diagnostics)
    tool = f"topology.{template.id}@{template.version}"
    now = clock.now()
    by_ref = {p.refdes: p for p in parts}
    stress: list[StressValue] = []
    for role, specs in out.stress.items():
        refs = [r for r in roles.parts_with_role(role) if r in by_ref and by_ref[r].id is not None]
        if not refs:
            sink.info(
                "M2_ROLE_UNASSIGNED", f"template produced rows for role '{role}' but no part has it"
            )
            continue
        for s in specs:
            share = len(refs) if (role, s.param) in _SPLIT_PARAMS and len(refs) > 1 else 1
            if share > 1:
                sink.warning(
                    "M2_EQUAL_SHARING",
                    f"{role} {s.param}: {s.value:.3g} {s.unit} split equally among "
                    f"{', '.join(refs)} (ESR/ESL split is a Tier 2 prompt)",
                )
            for r in refs:
                part = by_ref[r]
                assert part.id is not None
                stress.append(_bind(s, part.id, share, tool, template.version, now))

    prompts = [_prompt_for(name, roles, by_ref, template) for name in dict.fromkeys(out.needs)]
    return TemplateStress(stress, [p for p in prompts if p], inferred, params, list(sink.items))


def answer_prompt(  # noqa: PLR0917
    prompt: ValuePrompt, value: float, unit: str, source: Source, note: str, clock: Clock
) -> StressValue:
    """Typed Tier 2 answer (OPC-13). ``source`` is simulated/measured; ``note`` names the tool."""
    if source not in (Source.SIMULATED, Source.MEASURED):
        msg = "prompt answers are 'simulated' or 'measured'"
        raise ValueError(msg)
    if prompt.part_id is None:
        msg = "prompt has no part; attach it to a part before answering"
        raise ValueError(msg)
    return StressValue(
        part_id=prompt.part_id,
        param=prompt.param,
        value=value,
        unit=unit,
        stat=Stat(prompt.stat),
        scenario=prompt.scenario,
        source=source,
        tier=Tier.T2,
        tool=f"prompt:{note or 'user'}",
        tool_version="-",
        timestamp=clock.now(),
        note=prompt.reason,
    )


def manual_stress(  # noqa: PLR0917
    part_id: int,
    param: str,
    value: float,
    unit: str,
    stat: Stat,
    clock: Clock,
    *,
    scenario: str = "nominal",
    pinned: bool = False,
    note: str | None = None,
) -> StressValue:
    """Spreadsheet-style manual entry (OPC-02): source=manual, tier=1, optional pin."""
    return StressValue(
        part_id=part_id,
        param=param,
        value=value,
        unit=unit,
        stat=stat,
        scenario=scenario,
        source=Source.MANUAL,
        tier=Tier.T1,
        tool="manual",
        tool_version="-",
        timestamp=clock.now(),
        pinned=pinned,
        note=note,
    )


# ----------------------------------------------------------------------------- helpers


def _template_output(template: TopologyTemplate, params: Mapping[str, float]) -> Any:
    full = getattr(template, "compute_full", None)
    if callable(full):
        return full(params)
    # Minimal adapter for templates that only implement the ABC.
    diags = template.validity_checks(params)
    stress = {} if any(d.severity is Severity.ERROR for d in diags) else template.compute(params)
    return type("Out", (), {"stress": stress, "needs": [], "diagnostics": diags})()


def _ic_params(parts: list[Part], roles: RoleMap) -> dict[str, float]:
    """Part parameters the template may use, taken from ratings (M1 provenance)."""
    by_ref = {p.refdes: p for p in parts}
    out: dict[str, float] = {}
    for role, prefix in (("ic", ""), ("high_side_switch", "hs"), ("low_side_switch", "ls")):
        for r in roles.parts_with_role(role):
            part = by_ref.get(r)
            if part is None:
                continue
            for src, dst in (
                ("rds_on_hs", "rds_hs"),
                ("rds_on_ls", "rds_ls"),
                ("rds_on", f"rds_{prefix}" if prefix else None),
                ("eta", "eta"),
                ("p_sw", "p_sw"),
                ("theta_ja", "theta_ja"),
            ):
                rating = part.ratings.get(src)
                if rating is not None and dst:
                    out.setdefault(dst, rating.value)
    for r in roles.parts_with_role("catch_diode"):
        vf = by_ref[r].ratings.get("vf") if r in by_ref else None
        if vf is not None:
            out.setdefault("vd", vf.value)
            out.setdefault("synchronous", 0.0)
    if roles.parts_with_role("catch_diode") and not roles.parts_with_role("low_side_switch"):
        out.setdefault("synchronous", 0.0)
    return out


def _bind(  # noqa: PLR0917
    s: StressSpec, part_id: int, share: int, tool: str, version: str, now: Any
) -> StressValue:
    note = s.note
    if share > 1:
        note = f"{note + '; ' if note else ''}1/{share} of the role total (equal sharing assumed)"
    return StressValue(
        part_id=part_id,
        param=s.param,
        value=s.value / share,
        unit=s.unit,
        stat=s.stat,
        scenario=s.scenario,
        source=Source.EQUATION,
        tier=Tier.T1,
        tool=tool,
        tool_version=version,
        timestamp=now,
        note=note,
    )


def _template_part_inputs(
    template: TopologyTemplate, parts: list[Part], roles: RoleMap, params: Mapping[str, float]
) -> dict[str, float]:
    """Template-declared ``part_inputs`` (param -> (role, rating)) read from part ratings, so a
    topology plugin can use e.g. a transformer turns ratio without M2 knowing the topology."""
    by_ref = {p.refdes: p for p in parts}
    out: dict[str, float] = {}
    for param, (role, rating) in getattr(template, "part_inputs", {}).items():
        if param in params:
            continue
        for r in roles.parts_with_role(role):
            found = by_ref[r].ratings.get(rating) if r in by_ref else None
            if found is not None:
                out[param] = found.value
                break
    return out


def _prompt_for(
    name: str, roles: RoleMap, by_ref: Mapping[str, Part], template: TopologyTemplate | None = None
) -> ValuePrompt | None:
    """Prompt for a value the template needs; the template's own ``prompt_specs`` win."""
    own = getattr(template, "prompt_specs", {}).get(name)
    if own is not None:
        role, param, stat, reason, how = own
    elif name in _PROMPT_TEXT:
        param, stat, reason, how = _PROMPT_TEXT[name]
        role = {"p_ic": "ic", "p_sw": "ic", "dcr": "inductor", "vd": "catch_diode"}[name]
    else:
        return None
    refs = roles.parts_with_role(role)
    part = by_ref.get(refs[0]) if refs else None
    return ValuePrompt(
        part_id=part.id if part else None,
        param=param,
        stat=stat,
        scenario="vin_max",
        reason=reason,
        how_to_obtain=how,
        origin=PromptOrigin.M2,
    )
