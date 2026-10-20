# Hand-off: goal, state, architecture, decisions, open issues, next step

Last updated after the T35–T37 session (M3 triage, Tier 2 CSV, Refine + Compare Runs). Read
`AGENTS.md` first (rules), then this file. Update this file at the end of every session.

---

## 1. Goal and current state

**Goal.** Offline Windows desktop "Design for Reliability Toolkit" (PRD in the owner's
Downloads: `Design_for_Reliability_Toolkit___PRD.md`): import BOM + netlist, recognise the
converter topology, compute Tier 1 stress, derate, solve thermal, triage, lifetime, failure
rate, FMEA, report. Built so modules/topologies/screens/report sections can be added or removed
by adding or deleting a folder, with no edits elsewhere.

**State.** PRD MVP tasks T01–T25 complete, the owner-requested part catalog, and now the first
v1 slice T35–T37. Remaining v1: M7 lifetime (T29–T31), M8 failure rate (T32–T34), other
topologies (T26–T28), M9 FMEA/validation (T38–T40); v2 (T41–T44) not started.

| Area | Status |
| --- | --- |
| Core contracts, registry, DB, per-module Alembic branches, orchestrator | done |
| M1 BOM (Altium `.BomDoc`) + Protel netlist import, classifier, catalog, pin functions | done |
| M12 topology match/propose/confirm; `buck` + `buck_integrated` patterns and templates | done |
| M2 conditions (spec, inference, prompts, manual/T2 entry, **Tier 2 CSV import**) | done |
| **M3 triage** (F0/F1/F2/F4, PRD 3.3 ranking, waivers, M3 prompts, `m3_refinement_item`) | done |
| M5 derating (`generic_conservative` YAML, all factors `verify`) | done |
| M6 thermal (θ chain, Rds_on(Tj) fixed point, runaway) | done |
| M11 HTML report (100 % badged numbers), PDF via QtWebEngine | done |
| PySide6 shell + 11 screens (…, **Refine**, **Compare Runs**) + PRD 2.6 workflow states | done |
| Packaging: PyInstaller spec, launcher, Inno script, build script | done (built once; ISCC not installed) |
| M7 lifetime, M8 failure rate, other topologies, M9 FMEA, M10 Monte Carlo | not started |

Quality gates at head: ~250 tests, 96 % coverage (gate 85 %), mypy strict clean (155 files),
import-linter 3/3, UI token lint clean, subtractive matrix (each optional module deleted in
turn, now including `m3_triage`) — see the commit message / CI for the final run.

Design C (the only real board; fixtures in `tests/fixtures/design_c/`) operating point from the
owner: Vin 7–22 V, Vout 3.3 V, Iout 3.25 A, fsw 400 kHz, Ta 20 °C. Expected Tier 1 result:
0 FAIL, 2 WARN (C2 `cap_ceramic_voltage`, U3 `ic_iout`), 3 UNKNOWN (L1 `i_sat`, U3 `v_in_max`,
U3 `i_limit`), 4 PASS, one M2 prompt (U3 `p_loss`). **Triage result:** ranked U3 1.20
(F0, F1, F4 sw_vds_ringing) > L1 0.75 (F0, F1 i_rms 97 %, F4 load-step Isat) > C2 0.44
(F1, F4 inrush) > C1 0.16 (F1 12 % margin, F4 inrush); 4 M3 prompts (so 5 open prompts total).

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
   (pipeline now ends with `m3_triage`) and `python -m dfr gui` (File → Exit).

## 3. Architecture and key names

Layers (import-linter enforced, downward only):
`dfr.ui → dfr.app → dfr.modules | dfr.topologies → dfr.api → dfr.core`.
Modules never import each other; they exchange `dfr.core.contracts` types through the
orchestrator capability bag and expose callables via `ModuleSpec.services`.

**Core**
- `dfr/core/contracts/v1/` — frozen pydantic models: `Part`, `Rating`, `RatingSet`,
  `StressValue` (+`StressKey`, `StressSpec`), `ConverterSpec`, `ValuePrompt`, `Stage`,
  `RoleMap`, `RoleProposal`, `PatternMatch`, `DeratingResult`, `ThermalResult`,
  `RefinementItem` (now has `id`), `AnalysisRun`, `RunConfig`, `Diagnostic`; enums incl.
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
  tier_level)` — finds the confirmed stage, loads role map/templates/ruleset via services and
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
- `m5_derating`, `m6_thermal`, `m11_report`, `_example` — unchanged.

**Topologies**: `dfr/topologies/buck/` (`BuckPattern`, `BuckTemplate`, `buck_point`).

**UI** (PySide6, optional extra `gui`)
- `dfr/ui/tokens.py` (only colors), `dfr/ui/shell/` (`MainWindow`, panels, theme, `run_gui`).
- `dfr/ui/viewmodels/shell.py::ShellViewModel` — session, registry, `step_status`,
  **`workflow_state: Property[SessionState]`**, `select`, `post`, `refresh_runs` (sets
  TRIAGED when runs exist), `mark_downstream_stale`.
- `dfr/ui/viewmodels/workspace.py::Workspace` — `import_files`, `run_match`, `confirm`,
  `set_spec`, `run_tier1(config, *, parent_run_id, tier_level)`, **`rerun()`** (parent = current
  run, Tier 2), **`note_t2_input()`** (→ `T2_QUEUED`, analyze STALE), **`import_t2_csv(data,
  name)`**, **`mark_final()`** (→ `FINAL`); emits `changed("run" | "t2_input" | "final" | …)`.
- Screens (`dfr/ui/screens/<id>/screen.py`): home, catalog, import_design, parts, circuit,
  conditions, stress (answering a prompt now calls `note_t2_input`), results, **refine**
  (requires `m3_triage`: ranked items, waive/un-waive, Values Needed with `AnswerDialog`
  reused from the stress screen, Import Tier 2 CSV…, Re-run (Tier 2), Mark final),
  **compare** (requires `m5_derating`: two run pickers defaulting to (parent, latest), diff
  of derating + Tj rows, "Changed rows only", `MarginBar` with hollow T1 / solid T2), report.

**Data**: `data/rulesets/generic_conservative.yaml`, **`data/triage/default.yaml`**,
`data/schemas/{ruleset,catalog,triage}.schema.json`, `data/catalog/example_catalog.json`.
`DFR_DATA_DIR` overrides the folder (frozen app). The whole `data/` tree is bundled by the spec.

**Tests of note**: `tests/m3_triage/test_m3.py` (hand-calculated scores, F0/F2/F4, TRI-03/04),
`test_m3_persist.py` (orchestrator with a fake derating step, prompts stored once, waivers),
`test_refine_gui.py` (full GUI loop incl. Compare Runs; lives under `tests/m3_triage/` so the
subtractive run deletes it with the module), `tests/m2_conditions/test_csv_import.py`,
`tests/ui/test_workflow_vm.py` (Qt-free state machine T1 → CSV → re-run → final).

## 4. Decisions made, and approaches rejected (with reasons)

Owner decisions (do not re-ask):
- **v1 order**: M3 triage + CSV Tier 2 + Compare Runs (T35–T37, done) → M7 lifetime (T29–T31)
  → M8 failure rate (T32–T34) → other topologies (T26–T28) → M9 FMEA/validation (T38–T40).
- **MIL-HDBK-217F / SR-332**: ship the engine with empty tables and a documented import format.
- **Lifetime constants**: seed defaults marked `verify`, low confidence; every result shows the
  constant's source and confidence; constants in `data/`, never in code.
- **Part data source**: local catalog; online lookup deferred to v2 behind the `Network` port.
- Dev Python 3.14; installer bundles 3.12 per PRD (CI tests both).
- Hand-off doc wins over the PRD where they differ.

Engineering decisions (this session):
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
13. **Report has no triage section yet.** M11 consumes `report.sections` services but
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

Session gotcha: running `ruff format` between two text-replacement edits changes the anchor
text of the second edit. Make all replacements, then format. On this machine the venv is used
from Git Bash as `.venv/Scripts/python -m …` (backslash paths fail there).

## 6. Immediate next step: T29–T31 (M7 lifetime)

Create `dfr/modules/m7_lifetime/` (copy `_example`), `data/models/lifetime/*.yaml` with a
JSON Schema, tests in `tests/m7_lifetime/`.

1. **Models as `LifetimeModel` plugins** (`dfr/core/extension.py::LifetimeModel` exists:
   `applies_to(part)`, `estimate(part, stress, thermal, profile) -> LifetimeResult`):
   electrolytic Arrhenius (`L = L0 · 2^((T0 − Tcore)/10)` with ripple factor), MLCC
   voltage/temperature acceleration (Prokopowicz, exponents `verify`), semiconductor
   Coffin–Manson/Norris–Landzberg from `ThermalResult.delta_tj_cycles`. Constants in
   `data/models/lifetime/` with `source` + `confidence`, every result shows them
   (owner decision). No thermal/θ → `life_hours=None`, `Confidence.LOW`, never a guess.
2. **Mission profile**: a small `MissionProfile` contract (ambient histogram, on/off cycles,
   target life years) entered on the Conditions screen; default profile marked `verify`.
3. Step `requires=("parts", "effective_stress")`, `optional_requires=("thermal",)`,
   `provides=("lifetime",)`; table `m7_lifetime_result`; service `load_lifetime_results`.
4. Then M3 F3 (`w3·clamp(1 − life/target)`) reads `ctx.get_or("lifetime")` — add
   `"lifetime"` to M3 `optional_requires` and a test; Results/Report sections for life.
5. Update `docs/architecture.md`, `README.md`, this file; full gate; commit; push; check CI.
