# Rules for working in this repository

These apply to humans and coding agents alike. They encode PRD section 2.7 (modularity).

## Commands

- Setup: `python -m venv .venv && .venv\Scripts\python -m pip install -e ".[dev]"`
- Full check before any commit (all must pass):
  `ruff check . && ruff format --check . && mypy && lint-imports && pytest --cov && python scripts/subtractive_test.py && python scripts/check_ui_tokens.py`
- Windows consoles: set `PYTHONUTF8=1`.
- Build the app: `pip install pyinstaller && python scripts/build_installer.py [--skip-inno]`
  (writes git-ignored `build/` and `dist/`, ~1 GB; delete them when done).
- New migration: `python scripts/new_migration.py core "msg" --autogenerate` or
  `python scripts/new_migration.py <module_id> "msg"` (module tables are written by hand).

## Layering (enforced by import-linter)

`dfr.ui` → `dfr.app` → `dfr.modules` | `dfr.topologies` → `dfr.api` → `dfr.core`.
Imports go downward only. A module never imports another module; they exchange
`dfr.core.contracts` types through the orchestrator's capability bag.

## Adding things

- **Module**: new folder `dfr/modules/<id>/` with `module.py` exposing `MODULE: ModuleSpec`
  (`requires`/`provides` capability names, `step` function, optional `migrations_path` whose
  branch label equals the module id). Tests in `tests/<id>/`. Nothing outside the folder changes.
  Copy `dfr/modules/_example/` to start.
- **Topology**: new folder `dfr/topologies/<id>/` with a `TopologyPattern`, a `TopologyTemplate`
  naming that pattern, and its data files.
- **Screen**: folder `dfr/ui/screens/<id>/screen.py` with `SCREEN: ScreenSpec` and `build(vm)`.
  Hidden when `SCREEN.requires` modules are absent. Views call registry services only.
- **Report section**: a `(ReportSectionSpec, render)` pair returned by a module's
  `report.sections` service; `render(RunBundle) -> str` and every number goes through `num()`.
- **Service**: add a callable to `ModuleSpec.services`; consumers use `registry.service(name)`.
  Never import another module's package, not even from the UI.
- **Contract change**: additive fields go in `contracts/v1`; breaking changes create
  `contracts/v2` and keep v1 for one release. Bump `API_VERSION` only for breaking changes.

## Non-negotiables

- Modules are pure functions of their inputs. No global state. Side effects (clock,
  filesystem, network) go through `dfr.core.ports`; the default network port is `NoNetwork`.
- Never raise on bad part data. Emit a `Diagnostic` and skip the part. Parsers report
  line-numbered diagnostics.
- Never guess a value the app cannot compute or look up: create a `ValuePrompt`.
  Missing ratings yield `UNKNOWN`/`F0 no data`, never `PASS`.
- Every stress value, rating and model constant carries source/provenance, tier, tool and
  tool_version, timestamp. Results store the stress-value ids they used.
- `analysis_run` and `stress_value` rows are immutable once written. Re-runs create a new
  run with `parent_run_id`.
- Numeric constants (derating factors, lifetime/failure-rate parameters) live in `data/`
  files, never in code, each with a source citation. Anything unverified is marked `verify`.
- Do not commit MIL-HDBK-217F or SR-332 tables until licensing is cleared.
- Equation code cites its source (PRD section and/or document, page) in the docstring and
  has at least three hand-calculated test cases at 0.1% tolerance.
- UI: views hold no logic; view-models are plain Python; all colors come from `dfr/ui/tokens.py`.
  Beware Qt name clashes on QWidget/QDialog subclasses (`render`, `result`, `update`, `close`);
  mypy flags them, name your methods/attributes differently.
- Keep files under ~400 lines; split rather than grow.
- Do not create or delete anything outside this repository folder.

## Part catalog

User-supplied ratings/pinouts live in M1's `m1_part_catalog` (per-MPN, grouped in datasets).
Format, rating names and merge/delete semantics: `docs/catalog_format.md`. New rating names a
rule or model reads must be added to that table.

## Fixtures

`tests/fixtures/design_c/` holds the only real CAD exports (Altium Protel netlist + BomDoc).
They are byte-exact (CRLF, Latin-1) and must never be edited or re-encoded.
