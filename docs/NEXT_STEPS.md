# Hand-off: goal, state, architecture, decisions, open issues, next step

Last updated after the T32–T34 session (M8 failure rate + surfacing M3/M7 in the report and
Results screen), which followed T29–T31 (M7 lifetime) and T35–T37 (M3 triage, Tier 2 CSV,
Refine + Compare Runs). Read `AGENTS.md` first (rules), then this file. Update this file at
the end of every session.

---

## 1. Goal and current state

**Goal.** Offline Windows desktop "Design for Reliability Toolkit" (PRD in the owner's
Downloads: `Design_for_Reliability_Toolkit___PRD.md`): import BOM + netlist, recognise the
converter topology, compute Tier 1 stress, derate, solve thermal, triage, lifetime, failure
rate, FMEA, report. Built so modules/topologies/screens/report sections can be added or removed
by adding or deleting a folder, with no edits elsewhere.

**State.** PRD MVP tasks T01–T25 complete, the owner-requested part catalog, v1 slices
T35–T37 (triage), T29–T31 (lifetime) and T32–T34 (failure rate). Remaining v1: other
topologies (T26–T28), M9 FMEA/validation (T38–T40), MTB-05 in-app comparison screen; v2
(T41–T44) not started.

| Area | Status |
| --- | --- |
| Core contracts, registry, DB, per-module Alembic branches, orchestrator | done |
| M1 BOM (Altium `.BomDoc`) + Protel netlist import, classifier, catalog, pin functions | done |
| M12 topology match/propose/confirm; `buck` + `buck_integrated` patterns and templates | done |
| M2 conditions (spec, inference, prompts, manual/T2 entry, **Tier 2 CSV import**) | done |
| **M3 triage** (F0/F1/F2/F3/F4, PRD 3.3 ranking, waivers, M3 prompts, `m3_refinement_item`) | done |
| M7 lifetime (electrolytic/polymer rule, MLCC P-V, Coffin–Manson+Miner, connector; `m7_lifetime_result`) | done, incl. Results-screen table + report section |
| **M8 failure rate** (table-driven parts-stress engine for 217F/SR-332 with **empty shipped tables**, PoF Weibull roll-up with MTTF/B10, series system; `m8_failure_rate_result`) | engine, persist, report section, Results summary line done; no dedicated screen (MTB-05 panel is in the report only) |
| M5 derating (`generic_conservative` YAML, all factors `verify`) | done |
| M6 thermal (θ chain, Rds_on(Tj) fixed point, runaway) | done |
| M11 HTML report (100 % badged numbers), PDF via QtWebEngine; **module sections via `report.bundle_extras` + `report.sections`** | done |
| PySide6 shell + 11 screens (…, **Refine**, **Compare Runs**) + PRD 2.6 workflow states | done |
| Packaging: PyInstaller spec, launcher, Inno script, build script | done (built once; ISCC not installed) |
| Other topologies, M9 FMEA, M10 Monte Carlo | not started |

Quality gates at head: ~320 tests, ~96 % coverage (gate 85 %), mypy strict clean (173 files),
import-linter 3/3, UI token lint clean, subtractive matrix (8 optional folders incl.
`m8_failure_rate`) — see the commit message for the last local result.

Design C (the only real board; fixtures in `tests/fixtures/design_c/`) operating point from the
owner: Vin 7–22 V, Vout 3.3 V, Iout 3.25 A, fsw 400 kHz, Ta 20 °C. Expected Tier 1 result:
0 FAIL, 2 WARN (C2 `cap_ceramic_voltage`, U3 `ic_iout`), 3 UNKNOWN (L1 `i_sat`, U3 `v_in_max`,
U3 `i_limit`), 4 PASS, one M2 prompt (U3 `p_loss`). **Triage result:** ranked U3 1.20
(F0, F1, F4 sw_vds_ringing) > L1 0.75 (F0, F1 i_rms 97 %, F4 load-step Isat) > C2 0.44
(F1, F4 inrush) > C1 0.16 (F1 12 % margin, F4 inrush); 4 M3 prompts (so 5 open prompts total).
With M7 present each of those gains +0.125 (lifetime "not available" → F0) and 16 more parts
appear at 0.125: every MLCC lacks a qualification point, every semiconductor lacks Tj (no θ),
every connector lacks `mating_cycles`. Design C has **no vendor lifetime data**, so M7 returns
19 × "not available" and 0 estimates — correct per LIF-06/TRI-05; the Refine list says why.
**M8 on Design C:** `mil_hdbk_217f n/a` and `sr_332 n/a` (empty shipped tables → every part
excluded with "no table entry"), `pof` "nothing to roll up" (no M7 estimates). The Results
summary line and the report's "Failure rate and MTBF" section say exactly that; no number is
invented. A filled table (format in `docs/failure_rate_tables.md`) turns the 217F line into
λ_sys/MTBF immediately.

## 2. First 10 minutes of the next session

1. `git status` clean; `git log -1` shows the T35–T37 commit or later.
2. CI for head: `curl -s https://api.github.com/repos/microsoftcodemaker/EXDesigner/actions/runs?per_page=2`
   then `.../actions/runs/<id>/jobs` for failing step names. Past CI failures and fixes:
   `ce0440c` (subtractive deleted module but not its tests → script deletes `tests/<module>/`
   too), `c11a440` (pytest-qt in `dev` extra crashed pytest without Qt → moved to `gui` extra),
   `f2dadf8` (Jinja2 in `gui` extra but M11 needs it → runtime dep).
3. Full gate (Windows: `set PYTHONUTF8=1`; GUI tests: `set QT_QPA_PLATFORM=offscreen`; in Git
   Bash use `.venv/Scripts/python -m ruff …` etc.):
   `ruff check . && ruff format --check . && mypy && lint-imports && pytest --cov && python scripts/subtractive_test.py && python scripts/check_ui_tokens.py`
   (the subtractive run takes ~10 min on this machine: 6 optional folders × full suite).
4. Smoke: `python -m dfr analyze --bom tests/fixtures/design_c/design_c.BomDoc --netlist tests/fixtures/design_c/design_c_protel.net --topology buck_integrated --vin-min 7 --vin-max 22 --vout 3.3 --iout 3.25 --fsw 400e3 --ta 20`
   (pipeline: example, m2, m6, m5, m7_lifetime, **m8_failure_rate**, m3_triage) and
   `python -m dfr gui` (File → Exit).

## 3. Architecture and key names

Layers (import-linter enforced, downward only):
`dfr.ui → dfr.app → dfr.modules | dfr.topologies → dfr.api → dfr.core`.
Modules never import each other; they exchange `dfr.core.contracts` types through the
orchestrator capability bag and expose callables via `ModuleSpec.services`.

**Core**
- `dfr/core/contracts/v1/` — frozen pydantic models: `Part`, `Rating`, `RatingSet`,
  `StressValue` (+`StressKey`, `StressSpec`), `ConverterSpec`, `ValuePrompt`, `Stage`,
  `RoleMap`, `RoleProposal`, `PatternMatch`, `DeratingResult`, `ThermalResult`,
  `RefinementItem` (now has `id`), **`MissionProfile`** (`target_life_years`,
  `operating_hours_per_year`, `on_off_cycles_per_year`, `mating_cycles_per_year`,
  `t_ambient_off`; property `target_life_hours`), `AnalysisRun`, `RunConfig`, `Diagnostic`; enums incl.
  `Tier`, `Source`, `RatingProvenance`, `DeratingStatus`, `PromptOrigin` (M2/M12/M3),
  `SessionState` (PRD 2.6 workflow). `API_VERSION`.
- `dfr/core/registry/` — `ModuleSpec` (`id, requires, optional_requires, provides, optional,
  step, persist, services, migrations_path, table_prefix`), `discover()`,
  `DiscoveryResult.service(name)` / `services_named(name)` / `has_service(name)`, pipeline
  builder with missing-dep/cycle diagnostics.
- `dfr/core/db/` — `base.py`, `models/` (core tables), `repos/` (`DesignRepo`, `PartRepo`,
  `NetlistRepo`, `StageRepo`, `StressRepo` incl. `resolve_effective_stress` precedence
  pinned-manual > T2 newest > T1, prompts `add_prompt/open_prompts/answer_prompt/skip_prompt`;
  `RunRepo` with `ImmutableRunError`, `chain()`, `effective_ids()`; `DiagnosticRepo`),
  `migrate.py`, `types.py::UtcDateTime`.
- `dfr/core/units.py`, `diagnostics.py` (`DiagnosticSink`, always truthy), `ports.py`,
  `circuit.py`, `equations/`, `extension.py` (`TopologyPattern`, `TopologyTemplate`,
  `ScreenSpec`, `ReportSectionSpec`, …).

**App**
- `dfr/app/orchestrator.py::Orchestrator.run_analysis` — plans pipeline, seeds `parts`,
  `effective_stress`, `config`, `clock` + `extra_context`, runs steps with crash isolation,
  calls each module's `persist`, re-resolves effective stress after a step provides `stress`,
  snapshots ids, freezes the run.
- `dfr/app/analysis.py::run_tier1(session, registry, AnalysisInputs, clock, parent_run_id,
  tier_level)` — `AnalysisInputs.profile: MissionProfile | None` → `mission_profile`
  capability; finds the confirmed stage, loads role map/templates/ruleset via services and
  **merges every `run_context(session, design_version_id)` service's mapping into the context**
  (how M3 gets its waivers and the open prompts without the app knowing M3).
- `dfr/app/workflow.py::import_design`, `match_and_confirm`; `catalog_report.py`; `__main__.py`.

**Modules** (`dfr/modules/<id>/module.py` exposes `MODULE`)
- `m1_bom`: BOM/netlist import, classifier, catalog (`CatalogRepo`, `catalog_io`), pins, persist.
- `m12_topology/service.py`: `match_topology`, `apply_edits`, `confirm_roles`, `role_map_for`, …
- `m2_conditions`: `infer.py`, `service.py` (`compute_template_stress`, `answer_prompt`,
  `manual_stress`), **`csv_import.py` (`parse_t2_csv`, `import_t2_csv`: columns
  `refdes,param,stat,scenario,value,unit,source,tool,note`, all-or-nothing, line-numbered
  diagnostics `T2_CSV_*`, stores `tier=2`, `tool="csv:<name> (<tool>)"`, `tool_version` =
  sha256[:12], answers a matching open prompt)**. `persist` now re-uses an open prompt instead
  of adding a duplicate on re-runs.
- **`m3_triage`**: `config.py` (`load_config("default")` from `data/triage/default.yaml`,
  JSON-Schema `data/schemas/triage.schema.json`, sha256, `TriageConfig`, `BlindSpot`),
  `engine.py::triage(parts, derating, cfg, effective, thermal, topology, roles,
  existing_prompts, waivers, sink)` → `RefinementItem`s sorted open-first by score;
  `module.py` (step, `persist` → `m3_refinement_item` rows + prompts via `StressRepo`,
  services `load_refinement_items`, `load_triage_waivers`, `waive_refinement`,
  `unwaive_refinement`, `run_context`; table `m3_waiver`). Migration `0001_m3_triage`.
- **`m7_lifetime`**: `constants.py` (`load_constants("default")` from
  `data/models/lifetime/default.yaml`, schema `lifetime.schema.json`, `LifetimeConstants`
  with `CapacitorRule`, `ProkopowiczVaskas`, `CoffinManson`; every block has `source` +
  `confidence`), `equations.py` (pure: `core_temperature`, `temperature_rule_life_hours`,
  `prokopowicz_vaskas_life_hours`, `coffin_manson_cycles`, `miner_life_hours`,
  `connector_life_hours`; 3+ hand-calculated cases each), `models.py` (`LifetimeModel`
  subclasses `CapacitorTemperatureRule(subtype, rule)`, `MlccVoltageTemperature`,
  `ThermalCyclingMiner`, `ConnectorMating`; `LifetimeContext(constants, profile, t_ambient)`
  is passed as the ABC's `profile` argument; `default_models(constants)`), `module.py`
  (`estimate_lifetimes(parts, effective, constants, *, thermal, profile, t_ambient, models,
  sink)`, step provides `lifetime` and echoes `mission_profile`, `persist` →
  `m7_lifetime_result`, services `estimate_lifetimes`, `load_lifetime_constants`,
  `load_lifetime_results`). Migration `0001_m7_lifetime`.
- **`m8_failure_rate`**: `tables.py` (`load_tables()` = every `data/models/failure_rate/*.yaml`
  keyed by id, `load_table(id)`, `load_table_file(path)`; one schema
  `failure_rate.schema.json` for both `method: parts_stress` and `method: pof_weibull`;
  `FailureRateTable` with `entries[(class, subtype)] -> Entry(form, lambda_b, c1, c2,
  factors)`, `Factor(kind=constant|lookup|arrhenius|stress_ratio|value_curve)`, `betas`,
  `entry_for`, `beta_for`, `is_empty`), `engine.py` (`arrhenius`, `interpolate`,
  `evaluate_factor`, `part_rate_fit`, `parts_stress(parts, effective, table, thermal, t_ambient,
  environment, quality) -> FailureRateResult` with per-part `excluded_reasons`),
  `pof.py` (`eta_from_life`, `weibull_rollup(lifetimes, table, target_life_h)` → MTTF by
  `np.trapezoid` on a log grid, B10, R(t) curve, per-part average hazard), `module.py`
  (`compute_failure_rates(...)`: `method=None` runs every table with data, each its own result;
  `persist` → `m8_failure_rate_result` (one row per method, per-part/curve as JSON);
  services `compute_failure_rates`, `load_failure_rate_tables`, `load_failure_rate_table`,
  `load_failure_rate_table_file`, `load_failure_rate_results`, `report.bundle_extras`,
  `report.sections`), `report.py` (per-method figures, top 15 contributors, exclusions,
  assumptions, PRD 3.8 comparison table). Migration `0001_m8_failure_rate`.
- `m11_report`: `load_bundle` merges every `report.bundle_extras(session, run_id)` service into
  `RunBundle.extras`; `num`/`table`/`muted`/`SOURCE_LABELS` moved to **`dfr/core/report.py`**
  and re-exported from `dfr.api` so any module can badge numbers (M11 imports them too).
- `m3_triage/report.py` (section `triage`, order 32: ranked open items with score badged by
  the part's worst stress tier, waived items with reason — TRI-03) and
  `m7_lifetime/report.py` (section `lifetime`, order 35: estimates sorted shortest-first with
  tier/source of the stress they used, "below target" verdict from the run's stored profile,
  "Not available" table with reasons). Both modules expose `report.bundle_extras`.
- `m5_derating`, `m6_thermal`, `_example` — unchanged.
- **Contracts (additive v1)**: `RunConfig.with_inputs(spec, profile)` stores both as JSON in
  `extra` (`SPEC_KEY`, `PROFILE_KEY`); properties `converter_spec` / `mission_profile` read
  them back — `run_tier1` always calls it, so every run row now carries its spec and profile.
  `FailureRateResult` gained `system_mttf_h`, `b10_h`, `table_id`, `confidence`,
  `excluded_reasons`.

**Topologies**: `dfr/topologies/buck/` (`BuckPattern`, `BuckTemplate`, `buck_point`).

**UI** (PySide6, optional extra `gui`)
- `dfr/ui/tokens.py` (only colors), `dfr/ui/shell/` (`MainWindow`, panels, theme, `run_gui`).
- `dfr/ui/viewmodels/shell.py::ShellViewModel` — session, registry, `step_status`,
  **`workflow_state: Property[SessionState]`**, `select`, `post`, `refresh_runs` (sets
  TRIAGED when runs exist), `mark_downstream_stale`.
- `dfr/ui/viewmodels/workspace.py::Workspace` — `import_files`, `run_match`, `confirm`,
  `set_spec(spec, overrides, profile=None)` (keeps `Workspace.profile`, default
  `MissionProfile()`), `run_tier1(config, *, parent_run_id, tier_level)`, **`rerun()`** (parent = current
  run, Tier 2), **`note_t2_input()`** (→ `T2_QUEUED`, analyze STALE), **`import_t2_csv(data,
  name)`**, **`mark_final()`** (→ `FINAL`); emits `changed("run" | "t2_input" | "final" | …)`.
- Screens (`dfr/ui/screens/<id>/screen.py`): home, catalog, import_design, parts, circuit,
  conditions (now with a **Mission profile** group: target life, operating hours, power
  cycles, connector matings), stress (answering a prompt now calls `note_t2_input`), results, **refine**
  (requires `m3_triage`: ranked items, waive/un-waive, Values Needed with `AnswerDialog`
  reused from the stress screen, Import Tier 2 CSV…, Re-run (Tier 2), Mark final),
  **compare** (requires `m5_derating`: two run pickers defaulting to (parent, latest), diff
  of derating + Tj rows, "Changed rows only", `MarginBar` with hollow T1 / solid T2), report.
  **Results** now has a third splitter pane "Lifetime (M7)" (`_build_lifetime_pane`,
  `_fill_lifetime`; hidden when M7 is absent; label names the catalog rating names to add) and
  the summary line ends with one clause per M8 method (`_failure_rate_line`).

**Data**: `data/rulesets/generic_conservative.yaml`, `data/triage/default.yaml`,
`data/models/lifetime/default.yaml`, **`data/models/failure_rate/{mil_hdbk_217f,sr_332,pof}.yaml`**
(the first two with `classes: {}`; format in `docs/failure_rate_tables.md`),
`data/schemas/{ruleset,catalog,triage,lifetime,failure_rate}.schema.json`,
`data/catalog/example_catalog.json`.
`DFR_DATA_DIR` overrides the folder (frozen app). The whole `data/` tree is bundled by the spec.

**Tests of note**: `tests/m8_failure_rate/test_engine.py` (dummy table
`dummy_parts_stress.yaml` with invented numbers; hand-calculated piT, curve interpolation,
product and `ic_sum` forms, every exclusion path, empty shipped tables), `test_pof.py` (MTTF =
η·Γ(1+1/β) and B10 closed forms at 0.1 %, two-mechanism series vs bisection),
`test_m8_module.py` (orchestrator with a fake M7, persist round-trip, method selection, report
section); `tests/m3_triage/test_m3_report.py`, `tests/m7_lifetime/test_m7_report.py` (fake
bundles; badge regex); `tests/m7_lifetime/test_equations.py` (hand calcs at 0.1 %),
`test_models.py` (datasheet-style electrolytic example, n/a paths, confidence),
`test_m7_persist.py`; `tests/m3_triage/test_m3.py` (hand-calculated scores, F0/F2/F3/F4, TRI-03/04),
`test_m3_persist.py` (orchestrator with a fake derating step, prompts stored once, waivers),
`test_refine_gui.py` (full GUI loop incl. Compare Runs; lives under `tests/m3_triage/` so the
subtractive run deletes it with the module), `tests/m2_conditions/test_csv_import.py`,
`tests/ui/test_workflow_vm.py` (Qt-free state machine T1 → CSV → re-run → final).

## 4. Decisions made, and approaches rejected (with reasons)

Owner decisions (do not re-ask):
- **v1 order**: M3 triage + CSV Tier 2 + Compare Runs (T35–T37, done) → M7 lifetime (T29–T31,
  engine done) → M8 failure rate (T32–T34) → other topologies (T26–T28) → M9 FMEA/validation
  (T38–T40).
- **MIL-HDBK-217F / SR-332**: ship the engine with empty tables and a documented import format.
- **Lifetime constants**: seed defaults marked `verify`, low confidence; every result shows the
  constant's source and confidence; constants in `data/`, never in code.
- **Part data source**: local catalog; online lookup deferred to v2 behind the `Network` port.
- Dev Python 3.14; installer bundles 3.12 per PRD (CI tests both).
- Hand-off doc wins over the PRD where they differ.

Engineering decisions (M8 session):
- **One table format for every constant-rate method.** 217F and SR-332 differ only in which
  π factors exist and their base-rate unit, so both are `method: parts_stress` files with
  named factors of five kinds (constant, lookup, arrhenius, stress_ratio, value_curve) and two
  forms (`product`, `ic_sum` for 217F microcircuits). Rejected: hard-coding the 217F part-class
  formulas in Python — the owner forbids transcribing the tables, and a user importing a table
  would still need code changes for each class.
- **Shipped 217F/SR-332 files are empty (`classes: {}`) and valid.** With no entry every part
  is excluded with a reason, system λ is `None`, the UI prints "n/a". Never a seeded number.
- **`failure_rate_method=None` runs every table that has data, one `FailureRateResult` each**
  (so constant-rate and wear-out are never summed — PRD 3.8 "mixing … is blocked"); a set
  method runs only that table; an unknown id is `FAILURE_RATE_NO_TABLE`. Output capability is
  therefore `list[FailureRateResult]`.
- **PoF reads an M7 life as η (63.2 %) by default** (`life_is: eta`; `b10` converts with
  `L/(−ln 0.9)^(1/β)`); betas per mechanism are seed data marked verify (low confidence).
  `PartFailureRate.lambda_fit` for PoF is the average hazard over the target life, labelled in
  `factors` — chosen over leaving the required field 0.
- **MTTF numerically** (`np.trapezoid` on 400 log points from 1 h to 10·max η, + t₀ for the
  R≈1 head) — 0.02 % off the closed form `η·Γ(1+1/β)`; closed form is not available for the
  series product.
- **Arrhenius without Tj falls back to Ta and says so** (assumption lists the refdes; a table
  can demand Tj with `requires_tj: true`, which excludes the part instead). Rejected: silently
  excluding every semiconductor on boards without θ data.
- **Report helpers moved to `dfr.core.report`** (re-exported by `dfr.api`) so M3/M7/M8 sections
  can badge numbers without importing M11 (import-linter independence contract). `RunBundle`
  stays in M11; sections duck-type it (`refdes`, `tier_source_for`, `effective`, `extras`).
- **Spec and profile persisted in `RunConfig.extra`** via `RunConfig.with_inputs` — needed by
  M7's report section for the target life, and is the first half of open bug #1 (reopen).
- Triage score in the report is badged with the part's worst effective-stress tier (it is a
  rank derived from those values, not a physical quantity).

Engineering decisions (M7 session):
- **Lifetime constants are data with confidence** (`data/models/lifetime/default.yaml`);
  part-specific data (L0/T0, dT0, MLCC qualification point `l1_hours/v1_test/t1_test`,
  `mating_cycles`) are catalog ratings (names added to `docs/catalog_format.md`). Missing
  part data → `life_hours=None`, `assumptions[0] = "not available: <why>"` (LIF-06);
  seed-constant use → `Confidence.LOW` (PRD 3.7). Electrolytic without `dt0_core` uses the
  file default and drops to LOW; without `i_ripple` while a ripple stress exists → n/a (the
  core rise cannot be scaled; chosen over a silent dT = 0). No ripple stress at all → dT = 0,
  stated as an assumption.
- **PyYAML gotcha**: `3.0e11` parses as a *string* (YAML 1.1 needs `3.0e+11`); the schema
  caught it (`'3.0e11' is not of type 'number'`). Write exponents with an explicit sign.
- **Thermal cycling without rainflow bins** (M6 does not emit `delta_tj_cycles` yet): one
  on/off cycle per `MissionProfile.on_off_cycles_per_year` with dTj = Tj − Ta_off, stated in
  the assumptions; rainflow bins are used when present.
- **`MissionProfile` is a frozen additive v1 contract** entered on the Conditions screen; the
  defaults (10 y, 8766 h/y, 365 cycles/y, 0 matings) are explicit assumptions echoed into the
  run (`mission_profile` capability) and the M7 summary diagnostic.
- **M3 F3**: `w3·clamp(1 − life/target)`; a model that returned "not available" adds an F0
  reason weighted `w3·no_lifetime_data` (0.5, new YAML weight, verify) — lower than a missing
  derating rating because on a board without vendor data every MLCC/semiconductor would
  otherwise outrank real WARN rows. The GUI test asserts only the top 4 of the ranking so it
  holds with and without M7.
- `LifetimeModel.estimate(..., profile)` receives a `LifetimeContext` (constants + profile +
  Ta) rather than widening the core ABC (no contract change).

Engineering decisions (T35–T37 session):
- **Triage follows PRD 3.3 literally**: `score = w1·clamp(1−margin/0.15) + w2·clamp(1−(Tjmax−Tj)/20)
  + w4·blind_spot_weight`, F0 (UNKNOWN rating) scores `w1·no_data` so missing data is never
  buried (TRI-05). F3 (lifetime) waits for M7; F5 (mode boundary) and F6 (events) need
  template/user data not yet exposed — thresholds already in the YAML. The hand-off's earlier
  "severity × sensitivity × uncertainty" sketch was dropped in favour of the PRD formula.
- **F4 blind-spot table is data** (`data/triage/default.yaml`, keyed by topology family +
  role + param/stat/scenario, each row with `source … (verify)`); each hit yields one
  `ValuePrompt(origin=M3)`, de-duplicated against M2's prompts of the same run and against
  prompts already open in the DB (PRD 2.6 step 4).
- **TRI-04 (don't re-flag refined reasons)**: a flag whose stress value(s) are already Tier 2
  is closed with `TRIAGE_ALREADY_REFINED`; F4 is closed when a T2 value exists at exactly
  (part, param, scenario).
- **Waivers persist per design version** in `m3_waiver` and take effect on the next run (an
  `analysis_run` is immutable, so the current run's items are not edited). Waived items stay
  in the list with status `waived` and the reason (TRI-03, report-ready).
- **`run_context` service hook** in `run_tier1`: generic way for a module to inject its own
  stored state into the run without the app importing it. Alternative rejected: giving steps
  the session (modules must stay pure functions of their inputs).
- **Tier 2 CSV is the reduced "one number per row" form**; the PRD's waveform CSV with window
  selection and RMS/peak computation (OPC-08) is a later task. A CSV row answers a matching open
  prompt so the Values Needed list shrinks either way.
- **M2 prompt de-duplication on re-run** (bug found by the new GUI test): M2 `persist` now
  returns the still-open prompt instead of inserting a duplicate.
- Worst-scenario rule in M5 means an answered `load_step` peak can become the stress shown in
  Compare Runs for `ind_isat` — intended, documented in the test.
- `tests/ui/test_screens_gui.py` counts prompts as `1 + 4·(m3 present)` so it passes with and
  without M3 (subtractive run).

Earlier decisions still in force: ruff `TCH` dropped; pint `to_preferred` replaced; ASCII
`ohm`; `DiagnosticSink.__bool__` True; screens discovered by folder; M11 reads other modules'
rows via services; subtractive test deletes `tests/<id>/`; catalog merge-and-take-ownership;
QtWebEngine kept; pytest-qt in `gui` extra; CLI auto-confirms roles, GUI never; WARN/FAIL
boundary (WARN while `stress <= rating`); avoid Qt name clashes (`render`, `result`, `update`).

## 5. Open bugs / known gaps (exact symptoms)

None fail tests; behaviours to fix or polish.

1. **Reopening a design from Home does not restore the import context.** `Workspace.imported`
   is only set by `import_files`; `reload_from_db` restores the confirmed stage but not
   `_graph/_parts/_hints`. Symptom: on Circuit Review, Match posts `UI_NO_IMPORT`. Fix: rebuild
   from `NetlistRepo`/`PartRepo` rows. Also `Workspace.spec` is not restored, so Re-run on the
   Refine screen after reopening posts `UI_NOT_READY` — **the spec and profile are now stored
   in every run row** (`run.config.converter_spec` / `.mission_profile`); `reload_from_db`
   only has to read the latest run's config into `Workspace.spec` / `.profile`.
2. **Catalog changes don't reach already-imported designs** (ratings resolved at BOM import).
3. **Results screen `MarginBar` column** (col 9) usually scrolled out of view; Compare Runs
   gives it a fixed 120 px width — do the same there.
4. **`CircuitScreen._candidate_changed`** compares the first rail's net name — brittle.
5. **Stress Table pin toggle silently no-ops** on non-manual rows.
6. **Thermal produces no rows for Design C** (`THERMAL_NO_THETA`), so F2 never fires on the
   real board until θJA ratings are catalogued; Results shows "0 thermal rows" with no pointer.
7. **GUI tests write real QSettings** (`HKCU\Software\EXDesigner\DfR Toolkit`).
8. **Git line-ending warnings** on commit for new text files; `.gitattributes` could declare
   `* text=auto eol=lf` except the byte-exact fixtures.
9. `example_catalog.json` has placeholder ratings marked verify.
10. Inno Setup not installed; `pyinstaller` not declared in `pyproject`.
11. No worker threads; UI blocks during runs (fine at 28 parts).
12. Pin-map library ships without seed entries for common 3-pin packages.
13. ~~Report/Results show no triage or lifetime rows~~ — done this session (sections `triage`,
    `lifetime`, `failure_rate`; Results Lifetime pane). Still missing: the **Results screen has
    no triage table** (Refine screen has it) and **no failure-rate panel** (MTB-05 asks for an
    in-app comparison panel; today only the summary line and the report section exist).
14. **F5/F6 flags not implemented**: F5 needs the CCM/DCM boundary margin from the template
    (`BuckPoint.boundary_margin` exists; expose it via `template_params`), F6 needs a per-design
    "expected events" setting (startup, load step, stall).
15. **Refine screen "force-add"** (TRI-03) not implemented; waive/un-waive only.
16. Iteration cap (`RunConfig.iteration_cap`, default 3) is stored but not enforced; the Refine
    screen never blocks a re-run.
17. **M7 gaps**: MLCC DC-bias C_eff (LIF-02 first half; needs a curve file format and a hook
    into M2's Cout inference), electrolytic `k(f)` frequency multiplier table (k = 1 assumed
    and stated), voltage factor Kv (off per PRD), solder-joint Norris–Landzberg (LIF-04 first
    half; needs test-cycle ratings `n_test, dt_test, f_test, tmax_test`), third-party
    `LifetimeModel` plugins (the ABC exists; M7 only runs `default_models`). M6 emits no
    rainflow bins (`ThermalResult.delta_tj_cycles` always empty): it has no mission phases.
18. `Workspace.profile` is not restored on reopen (same root cause as item 1; data now in the
    run row).
19. **M8 gaps**: `FailureRateModel` ABC (`dfr/core/extension.py`) is not consulted — M8 is
    table-driven only, third-party per-part models would need a `failure_rate.models` service
    hook; no k-of-n / parallel groups (PRD "could"); SR-332 Methods II/III (lab/field data
    Bayesian update) not implemented; the report's R(t) curves are stored (`reliability_curve`)
    but not drawn (no `ChartSpec` yet); `fr_environment` / `fr_quality` have no UI (only
    `RunConfig.extra`); no "import table" button (user copies the YAML into
    `data/models/failure_rate/`).
20. `tests/m8_failure_rate/test_m8_module.py::test_all_methods_persist_and_reload` compares
    `model_dump()` of stored vs live results — if `FailureRateResult` grows a non-JSON field the
    JSON round-trip (tuples → lists in `reliability_curve`) is where it will break.

Session gotcha: running `ruff format` between two text-replacement edits changes the anchor
text of the second edit. Make all replacements, then format. On this machine the venv is used
from Git Bash as `.venv/Scripts/python -m …` (backslash paths fail there).

## 6. Immediate next step: reopen fix, then T26–T28 (other topologies)

A. **Close open bug #1/#18 (small, high value now that the data exists):** in
   `Workspace.reload_from_db` read the newest run's `config.converter_spec` / `.mission_profile`
   into `self.spec` / `self.profile` (and set `last_outcome`-equivalents from the `load_*`
   services so Results/Refine render after reopen), and rebuild `_graph/_parts/_hints` from
   `NetlistRepo`/`PartRepo` so Match works. Add a GUI test: import → run → new window on the
   same DB → open Results/Refine → Re-run succeeds.
B. **T26–T28 other topologies**, one folder each under `dfr/topologies/` (copy `buck/`):
   boost, buck-boost/inverting, then flyback (needs transformer turns ratio from the catalog or
   a prompt). Each: `TopologyPattern` (graph signature: switch node, inductor placement,
   diode/sync-FET orientation), `TopologyTemplate` with the ideal CCM steady-state equations
   (PRD 3.2 tables), `validity_checks` (duty-cycle range, CCM boundary), 3+ hand-calculated
   tests per equation at 0.1 %, and a synthetic netlist fixture (no real CAD export exists for
   them — generate a Protel-format netlist in the test). M12 already fans out over
   `topology.patterns`; no app change expected. Watch M3's F4 blind-spot table: it is keyed by
   topology family, so add rows for `boost` / `buck_boost` in `data/triage/default.yaml` or F4
   silently yields nothing for them.
C. Then M9 FMEA (T38–T40): `data/fmea/` is an empty folder — write `fmea_library.yaml` + a
   schema first (mode fractions must sum to 1 per class, source recorded); the generator
   consumes M7 life + M8 `per_part` λ (FIT) for Occurrence through the editable threshold table.
D. Docs → full gate (`ruff check . && ruff format --check . && mypy && lint-imports && pytest --cov
   && python scripts/subtractive_test.py && python scripts/check_ui_tokens.py`; Git Bash:
   `.venv/Scripts/python -m …`, `.venv/Scripts/lint-imports`, `QT_QPA_PLATFORM=offscreen`,
   `PYTHONUTF8=1`; the subtractive matrix is now 8 folders, ~15 min) → commit with the usual
   trailer → push → check CI.
