# Hand-off: goal, state, architecture, decisions, open issues, next step

Last updated at commit `8f25558`. Read `AGENTS.md` first (rules), then this file. Update this
file at the end of every session.

---

## 1. Goal and current state

**Goal.** Offline Windows desktop "Design for Reliability Toolkit" (PRD in the owner's
Downloads: `Design_for_Reliability_Toolkit___PRD.md`): import BOM + netlist, recognise the
converter topology, compute Tier 1 stress, derate, solve thermal, triage, lifetime, failure
rate, FMEA, report. Built so modules/topologies/screens/report sections can be added or removed
by adding or deleting a folder, with no edits elsewhere.

**State.** PRD MVP tasks T01–T25 complete and pushed to `main` of
`https://github.com/microsoftcodemaker/EXDesigner`, plus the user part catalog (not in the PRD
task list; owner-requested). Not started: v1 (T26–T40) and v2 (T41–T44).

| Area | Status |
| --- | --- |
| Core contracts, registry, DB, per-module Alembic branches, orchestrator | done |
| M1 BOM (Altium `.BomDoc`) + Protel netlist import, classifier, catalog, pin functions | done |
| M12 topology match/propose/confirm; `buck` + `buck_integrated` patterns and templates | done |
| M2 conditions (spec, inference, prompts, manual/T2 entry) | done |
| M5 derating (`generic_conservative` YAML, all factors `verify`) | done |
| M6 thermal (θ chain, Rds_on(Tj) fixed point, runaway) | done |
| M11 HTML report (100 % badged numbers), PDF via QtWebEngine | done |
| PySide6 shell + 9 screens (Home, Catalog, Import, Parts, Circuit, Conditions, Results, Stress, Report) | done |
| Packaging: PyInstaller spec, launcher, Inno script, build script | done (built once; ISCC not installed) |
| Part catalog JSON/CSV datasets, missing-data report, CLI | done |
| M3 triage, CSV Tier 2, Compare Runs (T35–T37) | **next** |
| M7 lifetime, M8 failure rate, other topologies, M9 FMEA, M10 Monte Carlo | not started |

Quality gates at head: 233 tests, ~96 % coverage (gate 85 %), mypy strict clean (144 files),
import-linter 3/3 contracts kept, subtractive matrix passes with `_example`, `m11_report`,
`m6_thermal`, `buck` each deleted, UI token lint clean. CI (GitHub Actions: lint, test 3.12 +
3.14, no-qt, subtractive) was green at `f46efba`; `0bf435c`/`8f25558` were still running when
the session ended — **check them first**.

Design C (the only real board; fixtures in `tests/fixtures/design_c/`) operating point from the
owner: Vin 7–22 V, Vout 3.3 V, Iout 3.25 A, fsw 400 kHz, Ta 20 °C. Expected Tier 1 result:
0 FAIL, 2 WARN (C2 `cap_ceramic_voltage` 22 V on 35 V X7R at 0.5×; U3 `ic_iout` at 100 % of
3.25 A), 3 UNKNOWN (L1 `i_sat`, U3 `v_in_max`, U3 `i_limit` — no ratings), 4 PASS, one prompt
(U3 `p_loss`: no Rds_on/efficiency data).

## 2. First 10 minutes of the next session

1. `git status` clean; `git log -1` shows `8f25558` or later.
2. CI for head: `curl -s https://api.github.com/repos/microsoftcodemaker/EXDesigner/actions/runs?per_page=2`
   then `.../actions/runs/<id>/jobs` for failing step names. Past CI failures and fixes:
   `ce0440c` (subtractive deleted module but not its tests → `scripts/subtractive_test.py` now
   deletes `tests/<module>/` too), `c11a440` (pytest-qt in `dev` extra crashed pytest without
   Qt → moved to `gui` extra), `f2dadf8` (Jinja2 in `gui` extra but M11 needs it → runtime dep).
3. Full gate (Windows: `set PYTHONUTF8=1`; GUI tests: `set QT_QPA_PLATFORM=offscreen`):
   `ruff check . && ruff format --check . && mypy && lint-imports && pytest --cov && python scripts/subtractive_test.py && python scripts/check_ui_tokens.py`
4. Smoke: `python -m dfr analyze --bom tests/fixtures/design_c/design_c.BomDoc --netlist tests/fixtures/design_c/design_c_protel.net --topology buck_integrated --vin-min 7 --vin-max 22 --vout 3.3 --iout 3.25 --fsw 400e3 --ta 20`
   and `python -m dfr gui` (opens the window; File → Exit).

## 3. Architecture and key names

Layers (import-linter enforced, downward only):
`dfr.ui → dfr.app → dfr.modules | dfr.topologies → dfr.api → dfr.core`.
Modules never import each other; they exchange `dfr.core.contracts` types through the
orchestrator capability bag and expose callables via `ModuleSpec.services`.

**Core**
- `dfr/core/contracts/v1/` — frozen pydantic models: `Part`, `Rating`, `RatingSet`,
  `StressValue` (+`StressKey`, `StressSpec`), `ConverterSpec`, `ValuePrompt`, `Stage`,
  `RoleMap`, `RoleProposal`, `PatternMatch`, `DeratingResult`, `ThermalResult`,
  `RefinementItem`, `AnalysisRun`, `RunConfig`, `Diagnostic`; enums incl. `Tier`, `Source`,
  `RatingProvenance` (now has `CATALOG`), `DeratingStatus`, `PromptOrigin`. `API_VERSION`.
- `dfr/core/registry/` — `ModuleSpec` (`id, requires, provides, optional, step, persist,
  services, migrations_path, table_prefix`), `discover()` (folders + entry points +
  `%APPDATA%/DfR/plugins`), `DiscoveryResult.service(name)` / `services_named(name)` /
  `has_service(name)`, pipeline builder with missing-dep/cycle diagnostics.
- `dfr/core/db/` — `base.py` (`create_sqlite_engine`, `sqlite_url`, `MEMORY_URL`),
  `models.py` (core tables), `repos/` (`DesignRepo`, `PartRepo`, `NetlistRepo`, `StageRepo`,
  `StressRepo` incl. `resolve_effective_stress` precedence pinned-manual > T2 newest > T1,
  `RunRepo` with `ImmutableRunError`, `chain()`, `effective_ids()`, `DiagnosticRepo`),
  `migrate.py` (`upgrade_all`, `downgrade_all`, `is_up_to_date`; orphan branches kept),
  `types.py::UtcDateTime`.
- `dfr/core/units.py` (pint; `to_si`, `validate_unit`, ASCII `ohm`), `diagnostics.py`
  (`DiagnosticSink`, always truthy), `ports.py` (`Clock`, `FileSystem`, `Network`/`NoNetwork`),
  `circuit.py::CircuitIndex`, `equations/losses.py`, `equations/thermal.py::solve_tj`,
  `extension.py` (`TopologyPattern`, `TopologyTemplate`, `ScreenSpec`, `ReportSectionSpec`, …).

**App**
- `dfr/app/orchestrator.py::Orchestrator.run_analysis` — plans pipeline, seeds `parts`,
  `effective_stress`, `config`, `clock` + `extra_context`, runs steps with crash isolation,
  calls each module's `persist(session, run_id, result)`, re-resolves effective stress after a
  step provides `stress`, snapshots ids, freezes the run. `plan_pipeline`, `summarize`.
- `dfr/app/analysis.py::run_tier1(session, registry, AnalysisInputs, clock, parent_run_id,
  tier_level)` — finds the confirmed stage, loads role map/templates/ruleset via services.
- `dfr/app/workflow.py::import_design`, `match_and_confirm` — headless import → match →
  confirm (auto_confirm only for CLI/tests).
- `dfr/app/catalog_report.py::missing_data`, `format_missing`.
- `dfr/__main__.py` — `status | demo | analyze | gui | catalog import|export|list|delete|missing`.

**Modules** (`dfr/modules/<id>/module.py` exposes `MODULE`)
- `m1_bom`: `service.py` (`import_bom`, `classify_bom`), `bomdoc.py`, `description.py`
  (`parse_description`), `classifier.py`, `catalog.py` (`CatalogRepo`, `PartCatalogRow`,
  `CatalogImportRow`), `catalog_io.py` (`parse_catalog`, `import_catalog`, `export_catalog`,
  `delete_dataset`, `list_datasets`), `netlist/protel.py`, `join.py` (`join_netlist`,
  `prune_dnp`), `nets.py`, `pins.py` (`resolve_pin_functions`, `save_pinout`), `persist.py`,
  `data/class_defaults.yaml`. Migrations `0001_m1_bom`, `0002_m1_catalog_datasets`.
- `m12_topology/service.py`: `match_topology`, `apply_edits`, `confirm_roles`, `role_map_for`,
  `check_staleness`, `prefill_from_stale`.
- `m2_conditions`: `infer.py::infer_passives`, `service.py::compute_template_stress`,
  `answer_prompt`, `manual_stress`; step provides `stress, prompts, inferred_values,
  template_params`; persist writes stress rows + prompts.
- `m5_derating`: `ruleset.py` (`load_ruleset`, JSON-Schema validated YAML, sha256),
  `checker.py::evaluate_derating`, `load_results`; table `m5_derating_result`.
- `m6_thermal/module.py`: `solve_thermal`, `load_results`; table `m6_thermal_result`.
- `m11_report`: `module.py` (`build_report_html`, `write_report_html`, `load_bundle`),
  `sections.py` (`RunBundle`, `num()`, `SECTIONS`), `templates/report.html.j2`.
- `_example`: stub proving the drop-in contract.

**Topologies**: `dfr/topologies/buck/` — `pattern.py::BuckPattern` (variants `buck`,
`buck_integrated`), `inference.py::infer_pin_functions`, `equations.py::buck_point`,
`template.py::BuckTemplate`, `module.py` registers services `topology.patterns`,
`topology.templates`, `topology.inference`.

**UI** (PySide6, optional extra `gui`)
- `dfr/ui/tokens.py` — the only file allowed to contain colors (`DARK` default, `LIGHT`,
  Okabe-Ito status colors). `scripts/check_ui_tokens.py` enforces it.
- `dfr/ui/shell/` — `theme.py::build_qss`, `main_window.py::MainWindow` (menu, toolbar,
  document tabs, dock panels, status bar, QSettings layout), `panels.py` (`ProjectPanel`
  stepper, `PropertiesPanel`, `MessagesPanel`), `app.py::run_gui`.
- `dfr/ui/viewmodels/` (Qt-free): `observable.py` (`Signal`, `Property`), `shell.py`
  (`ShellViewModel`: session, registry, `step_status`, `select(Selection)`, `post()`,
  `refresh_runs`, `mark_downstream_stale`; `STEPS`, `StepStatus`), `workspace.py`
  (`Workspace`: `import_files`, `run_match`, `confirm`, `answer_pinout`, `set_spec`,
  `run_tier1`, `reload_from_db`; emits `changed(name)`).
- `dfr/ui/screens/<id>/screen.py` — each exposes `SCREEN = ScreenSpec(id, title, step, order,
  requires)` and `build(vm) -> QWidget`; discovered by `dfr/ui/screens/__init__.py::discover_screens`.
- `dfr/ui/kit/widgets.py` — `TierBadge`, `StatusChip`, `SourceTag`, `MarginBar`, `KeyValueGrid`.

**Data**: `data/rulesets/generic_conservative.yaml`, `data/schemas/{ruleset,catalog}.schema.json`,
`data/catalog/example_catalog.json`. `DFR_DATA_DIR` env var overrides the data folder (frozen app).

**Tooling**: `scripts/subtractive_test.py` (deletes each optional module + its tests, reruns
pytest; `--include-required`, `--only`), `scripts/new_migration.py`, `scripts/gen_core_baseline.py`,
`scripts/build_installer.py`, `packaging/{dfr.spec,launcher.py,installer.iss}`,
`.github/workflows/ci.yml`.

**Docs**: `README.md`, `AGENTS.md`, `docs/architecture.md` (capabilities + services tables),
`docs/catalog_format.md` (JSON/CSV formats, rating-name vocabulary), this file.

## 4. Decisions made, and approaches rejected (with reasons)

Owner decisions (do not re-ask):
- **v1 order**: M3 triage + CSV Tier 2 + Compare Runs (T35–T37) → M7 lifetime (T29–T31) →
  M8 failure rate (T32–T34) → other topologies (T26–T28) → M9 FMEA/validation (T38–T40).
- **MIL-HDBK-217F / SR-332**: ship the engine with empty tables and a documented import format
  (option a). Never transcribe tables from memory; SR-332 is paid.
- **Lifetime constants**: seed defaults marked `verify`, low confidence; every result shows the
  constant's source and confidence; owner replaces with vendor data (electrolytic L0/T0, MLCC
  DC-bias curves). Constants in `data/`, never in code.
- **Part data source**: local catalog (option 2) chosen. Online API lookup (Octopart/DigiKey)
  deferred to v2 behind the `Network` port opt-in (licensing, offline requirement). Bulk
  "database of the internet" rejected: distributor terms forbid redistribution, the needed
  fields (Rds_on, θJA, Isat, L0/T0) aren't reliably in parametric data, no provenance.
  Datasheet PDF extraction rejected: unreliable without an LLM, which the PRD excludes.
- Dev Python 3.14; installer bundles 3.12 per PRD (CI tests both).

Engineering decisions:
- Ruff `TCH` rule family dropped: conflicts with pydantic/SQLAlchemy runtime annotations.
- pint `to_preferred()` replaced by a dimensionality → unit table: `to_preferred` needs SciPy
  (`AttributeError: 'function' object has no attribute 'optimize'`). Units stored as ASCII
  `ohm` because `Ω` failed on the cp1252 console.
- `DiagnosticSink.__bool__` returns True: an empty sink was falsy and `sink or DiagnosticSink()`
  silently discarded callers' sinks (lost all diagnostics).
- Screens are discovered by folder under `dfr/ui/screens/`, not exported from `module.py`
  as the PRD sketched: modules sit below the UI layer and must not import Qt. `ScreenSpec`
  stays in core so modules *could* declare metadata, but the view lives in `ui`.
- M11 reads other modules' result rows via services (`load_derating_results`,
  `load_thermal_results`) rather than importing their ORM classes — keeps the no-cross-import
  rule and lets M11 run with M5/M6 deleted.
- Subtractive test deletes a module's `tests/<id>/` with it; required (`optional=False`)
  modules are skipped by default (`--include-required` forces). Rationale: a module's tests
  are part of the module per the PRD layout.
- Topology-specific tests live in `tests/topology_buck/` (incl. M2-binding tests) so deleting
  the buck folder keeps the suite green.
- Catalog: one row per MPN across datasets; a later import merges per rating/pin and takes
  ownership; deleting a dataset removes the entries it last wrote. Alternatives rejected:
  duplicate rows per dataset (lookup needs one answer per MPN; precedence between files would
  need UI), strict replace (silently drops ratings another file contributed).
- Catalog import is all-or-nothing on validation errors (no partial writes), every rating
  requires a `source` string (provenance is the product's core promise).
- QtWebEngine kept despite ~300 MB (PRD requires PDF of the HTML report; alternatives like
  reportlab/matplotlib PDF lose HTML fidelity and add deps). Mitigation: prune translations and
  non-English locales (−52 MB); unpacked 535 MB, LZMA installer expected ~200–250 MB.
- pytest-qt lives in the `gui` extra (crashes pytest at startup without a Qt binding);
  Jinja2 is a runtime dep (M11 is Qt-free).
- CLI `analyze` auto-confirms roles; the GUI never does (REC-06).
- `ruleset` WARN/FAIL boundary: WARN while `stress <= rating`, FAIL above the absolute rating
  (offset applies to the limit only) — the first implementation compared against
  `rating + offset`, which made Tj rules skip WARN.
- Qt name clashes: `QWidget.render` and `QDialog.result` were shadowed by my methods/attributes
  (caught by mypy). Renamed to `refresh` / `entry`. Avoid `update`, `close`, `show` too.

## 5. Open bugs / known gaps (exact symptoms)

None of these fail tests; all are behaviours to fix or polish.

1. **Reopening a design from Home does not restore the import context.** `Workspace.imported`
   is only set by `import_files`; `reload_from_db` restores the confirmed stage but not
   `_graph/_parts/_hints`. Consequence: on Circuit Review, Match posts
   `UI_NO_IMPORT: import a BOM and netlist first`, and `Conditions` works only if a stage
   was confirmed. Fix: rebuild `imported` from `NetlistRepo`/`PartRepo` rows (pins/nets are
   persisted), or store the import payload hash and reload lazily.
2. **Catalog changes don't reach already-imported designs** (documented in
   `docs/catalog_format.md` §"What happens on import"). Ratings are resolved at BOM import.
   Needs a "re-apply catalog to this version" action (new design version, re-run ratings).
3. **Results screen `MarginBar` column** (col 9) is usually scrolled out of view; give it a
   fixed width or move next to Status.
4. **`CircuitScreen._candidate_changed`** decides whether to re-match by comparing the first
   rail's net name (`self.ws.match.proposal.rails[0]`) — brittle; store the chosen index in
   `MatchState` instead.
5. **Stress Table pin toggle silently no-ops** on non-manual rows (`toggle_pin` returns when
   `v.source is not Source.MANUAL`); should post an info diagnostic.
6. **Thermal produces no rows for Design C** (`THERMAL_NO_THETA` warnings on every stressed
   part) because no θJA ratings exist. Expected per rules, but the Results screen shows
   "0 thermal rows" with no pointer to the Catalog screen.
7. **GUI tests write real QSettings** (`HKCU\Software\EXDesigner\DfR Toolkit`) because
   `MainWindow._settings()` isn't injectable; use `QSettings.setDefaultFormat`/temp scope in
   the `window` fixture.
8. **Git line-ending warnings** on commit (`LF will be replaced by CRLF`) for new JSON/YAML/
   spec files; `.gitattributes` could declare `* text=auto eol=lf` except the byte-exact
   fixtures (which are already `-text`).
9. `example_catalog.json` contains placeholders (`"i_sat": {"value": 0.0, ...}` marked verify);
   the owner will replace them from datasheets. `dfr catalog missing` lists 15 Design C parts.
10. Inno Setup not installed: `scripts/build_installer.py --skip-inno` verified; the `.iss`
    was never compiled. `pyinstaller` is installed in the venv but not declared in `pyproject`.
11. No worker threads: long operations run on the GUI thread. Fine for 28 parts; the PRD's
    200-part/5 s target (NFR-02 "UI never blocks > 200 ms") is unmeasured.
12. Pin-map library ships without seed entries for common 3-pin packages, so FETs/diodes
    always prompt until catalogued.

Session gotcha: running `ruff format` between two text-replacement edits changed the anchor
text of the second edit (happened twice). Make all replacements, then format.

## 6. Immediate next step: T35–T37 (M3 triage, CSV Tier 2, Compare Runs)

Create `dfr/modules/m3_triage/` (copy `_example`), `dfr/ui/screens/refine/` and
`dfr/ui/screens/compare/`, tests in `tests/m3_triage/` and `tests/ui/`. Nothing else changes
except `docs/architecture.md` tables and this file.

1. **Triage step** (`MODULE.requires=["parts", "effective_stress", "derating"]`,
   `optional_requires=["thermal"]`, `provides=["refinement"]`): priority =
   severity × sensitivity × uncertainty with weights in `data/triage/default.yaml`
   (JSON-Schema validated like the ruleset, all marked `verify`). Severity from
   `DeratingStatus`/margin; uncertainty from tier (T1 high, T2 low) and `UNKNOWN`;
   sensitivity from the template param that drives the stress (e.g. Isat ↔ ripple).
   Output `RefinementItem`s (contract exists in `contracts/v1/results.py`; extend additively
   if a field is missing) and `ValuePrompt(origin=PromptOrigin.M3)` for WARN/UNKNOWN or within
   10 % of a limit. Table `m3_refinement_item` on branch `m3_triage`
   (`python scripts/new_migration.py m3_triage "refinement items"`), `persist` hook like M5.
2. **CSV Tier 2 import** (service `import_t2_csv(session, clock, design_version_id, data,
   name)` in M2 — it owns stress entry): columns `refdes,param,stat,scenario,value,unit,source,
   tool,note`; validate refdes exists, `Stat`/`Source in {measured, simulated}`, unit via
   `validate_unit`; line-numbered diagnostics; all-or-nothing; writes `StressValue(tier=T2)`
   rows through `StressRepo.add` (T1 rows stay; precedence already handles it). Add a
   "Import Tier 2 CSV…" button to the Stress Table and Refine screens.
3. **Refine screen** (step `refine`): ranked `RefinementItem` list with reason text and
   "how to obtain"; actions answer prompt (reuse `AnswerDialog` from
   `dfr/ui/screens/stress/screen.py`), import CSV, skip; "Re-run" calls
   `Workspace.run_tier1(parent_run_id=last_run_id, tier_level=Tier.T2)` — add those parameters
   to `Workspace.run_tier1` (`dfr/app/analysis.py::run_tier1` already accepts them).
4. **Compare Runs screen**: two run pickers (`RunRepo.for_version`, `chain`), diff table of
   derating/thermal rows via `load_derating_results` / `load_thermal_results`; reuse the shape
   from `dfr/modules/m11_report/sections.py::render_refinement`. Add `MarginBar` with hollow
   T1 / solid T2 markers side by side.
5. **Workflow states** in `ShellViewModel`/`Workspace`: after a run, `refine` READY; after
   prompts answered / CSV imported → `T2_QUEUED`; after re-run → `TRIAGED`; a "Mark final"
   action → `FINAL` (PRD state machine). Map onto `StepStatus` or add a `workflow_state`
   `Property`.
6. Tests: hand-built derating inputs → expected ranking order; CSV with bad refdes/unit/
   source rejected with line numbers; GUI flow extends `tests/ui/test_screens_gui.py`
   (import → confirm → run → answer prompt → re-run → compare shows the changed row).
7. Then update `docs/architecture.md` (capabilities + services), `README.md` status, and this
   file; run the full gate; commit with the usual trailer; push; check CI.
