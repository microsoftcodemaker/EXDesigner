# Hand-off: goal, state, architecture, decisions, open issues, next step

Last updated after the T29–T31 session (M7 lifetime), which followed T35–T37 (M3 triage,
Tier 2 CSV, Refine + Compare Runs). Read
`AGENTS.md` first (rules), then this file. Update this file at the end of every session.

---

## 1. Goal and current state

**Goal.** Offline Windows desktop "Design for Reliability Toolkit" (PRD in the owner's
Downloads: `Design_for_Reliability_Toolkit___PRD.md`): import BOM + netlist, recognise the
converter topology, compute Tier 1 stress, derate, solve thermal, triage, lifetime, failure
rate, FMEA, report. Built so modules/topologies/screens/report sections can be added or removed
by adding or deleting a folder, with no edits elsewhere.

**State.** PRD MVP tasks T01–T25 complete, the owner-requested part catalog, v1 slices
T35–T37 (triage) and T29–T31 (lifetime engine). Remaining v1: M8 failure rate (T32–T34), other
topologies (T26–T28), M9 FMEA/validation (T38–T40); v2 (T41–T44) not started.

| Area | Status |
| --- | --- |
| Core contracts, registry, DB, per-module Alembic branches, orchestrator | done |
| M1 BOM (Altium `.BomDoc`) + Protel netlist import, classifier, catalog, pin functions | done |
| M12 topology match/propose/confirm; `buck` + `buck_integrated` patterns and templates | done |
| M2 conditions (spec, inference, prompts, manual/T2 entry, **Tier 2 CSV import**) | done |
| **M3 triage** (F0/F1/F2/F3/F4, PRD 3.3 ranking, waivers, M3 prompts, `m3_refinement_item`) | done |
| **M7 lifetime** (electrolytic/polymer rule, MLCC P-V, Coffin–Manson+Miner, connector; `m7_lifetime_result`) | engine + tests done; no Results/report rows yet |
| M5 derating (`generic_conservative` YAML, all factors `verify`) | done |
| M6 thermal (θ chain, Rds_on(Tj) fixed point, runaway) | done |
| M11 HTML report (100 % badged numbers), PDF via QtWebEngine | done |
| PySide6 shell + 11 screens (…, **Refine**, **Compare Runs**) + PRD 2.6 workflow states | done |
| Packaging: PyInstaller spec, launcher, Inno script, build script | done (built once; ISCC not installed) |
| M8 failure rate, other topologies, M9 FMEA, M10 Monte Carlo | not started |

Quality gates at head: ~290 tests, 96 % coverage (gate 85 %), mypy strict clean (162 files),
import-linter 3/3, UI token lint clean, subtractive matrix (7 optional folders incl.
`m3_triage` and `m7_lifetime`) green locally.

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
   (pipeline: example, m2, m6, m5, **m7_lifetime**, m3_triage) and `python -m dfr gui`
   (File → Exit).

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
- `m5_derating`, `m6_thermal`, `m11_report`, `_example` — unchanged.

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

**Data**: `data/rulesets/generic_conservative.yaml`, `data/triage/default.yaml`,
**`data/models/lifetime/default.yaml`**,
`data/schemas/{ruleset,catalog,triage,lifetime}.schema.json`, `data/catalog/example_catalog.json`.
`DFR_DATA_DIR` overrides the folder (frozen app). The whole `data/` tree is bundled by the spec.

**Tests of note**: `tests/m7_lifetime/test_equations.py` (hand calcs at 0.1 %),
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
   Refine screen after reopening posts `UI_NOT_READY` — store the spec with the run config
   (`RunConfig.extra`) or a `design_version` column and reload it.
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
13. **Report and Results screen show neither triage nor lifetime rows yet.** M11 consumes `report.sections` services but
    `render(RunBundle)` receives no session, so M3 cannot load its rows there. Options: let
    `load_bundle` call every `load_*` service it finds into `RunBundle.extras`, or add a
    `report.bundle_extras(session, run_id)` service hook. Waivers should then appear in the
    report (TRI-03).
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
18. `Workspace.profile` is not restored on reopen (same root cause as item 1).

Session gotcha: running `ruff format` between two text-replacement edits changes the anchor
text of the second edit. Make all replacements, then format. On this machine the venv is used
from Git Bash as `.venv/Scripts/python -m …` (backslash paths fail there).

## 6. Immediate next step: surface lifetime + triage, then T32–T34 (M8 failure rate)

A. **Make M7/M3 visible** (small; finishes T29–T31 end-to-end):
   1. Results screen: a "Lifetime" table (Part, Mechanism, Life years or "not available",
      Confidence, Assumptions) from `out.context.get_or("lifetime")` or
      `load_lifetime_results`; hint pointing at the Catalog screen and the rating names in
      `docs/catalog_format.md`.
   2. Report: give sections access to module rows. Simplest: `load_bundle` in
      `dfr/modules/m11_report/module.py` loops `registry.services_named("report.bundle_extras")`
      — each `(session, run_id) -> dict` merges into `RunBundle.extras`; M3 and M7 provide one;
      then M3/M7 expose `report.sections` returning `(ReportSectionSpec, render)` pairs that
      read `b.extras["refinement"]` / `b.extras["lifetime"]` (waivers with reasons, TRI-03;
      life with source + confidence per the owner decision). Every number through `num()`.
B. **M8 failure rate (T32–T34)**, `dfr/modules/m8_failure_rate/`: `FailureRateModel` plugins
   (`dfr/core/extension.py`), MIL-HDBK-217F parts-stress engine with **empty** tables + a
   documented import format (owner decision: never transcribe), SR-332 likewise, PoF Weibull
   roll-up from M7 `LifetimeResult`s, system series model; `FailureRateResult` contract exists.
   Table `m8_failure_rate_result`; `RunConfig.failure_rate_method` selects the model.
C. Docs/gate/commit/push/CI as usual.
