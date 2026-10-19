# Hand-off: where things stand and what to do next

Last updated at commit `0bf435c` (catalog import/export). Keep this file current at the end of
every working session; it is the first thing a new session should read after `AGENTS.md`.

## State

- MVP (PRD T01–T25) is complete: import → topology confirm → Tier 1 → derating/thermal →
  report → PySide6 app → PyInstaller packaging. Plus the user part catalog (JSON/CSV datasets).
- 233 tests, ~96 % coverage, mypy strict, import-linter, subtractive matrix all green locally.
- Design C golden operating point is real (7–22 V, 3.3 V / 3.25 A, 400 kHz, 20 °C):
  expected verdicts are in `tests/fixtures/design_c/README.md`.

## First 5 minutes of the next session

1. `git status` must be clean and `git log -1` should show `0bf435c` or later.
2. Check CI for the head commit: `https://github.com/microsoftcodemaker/EXDesigner/actions`
   (the API: `curl -s https://api.github.com/repos/microsoftcodemaker/EXDesigner/actions/runs?per_page=1`).
   If `no-qt` or `subtractive` fail, the usual cause is a dependency placed in the wrong
   extra or a test importing a module outside `tests/<module>/` (see git history of
   `cca5571`, `9f60449`, `da43c21`).
3. Run the full gate once (Windows: set `PYTHONUTF8=1`, GUI tests need `QT_QPA_PLATFORM=offscreen`):
   `ruff check . && ruff format --check . && mypy && lint-imports && pytest --cov && python scripts/subtractive_test.py && python scripts/check_ui_tokens.py`
4. Smoke: `python -m dfr analyze --bom tests/fixtures/design_c/design_c.BomDoc --netlist tests/fixtures/design_c/design_c_protel.net --topology buck_integrated --vin-min 7 --vin-max 22 --vout 3.3 --iout 3.25 --fsw 400e3 --ta 20`
   → 0 FAIL, 2 WARN (C2 cap voltage, U3 i_out), 3 UNKNOWN, 1 prompt (U3 p_loss).

## Decisions already made by the owner (do not re-ask)

- v1 order: **triage M3 + CSV Tier 2 import + Compare Runs (T35–T37) first**, then lifetime
  M7 (T29–T31), then failure rate M8 (T32–T34), then other topologies (T26–T28), then FMEA M9.
- MIL-HDBK-217F / SR-332: ship the engine with **empty tables** and a documented import
  format; the owner fills them. Never transcribe tables from memory.
- Lifetime constants: ship seed defaults **marked `verify`, low confidence**; every result must
  display the constant's source and confidence; owner replaces with vendor data (electrolytic
  L0/T0, MLCC DC-bias curves) over time. Constants live in `data/`, never in code.
- Online part lookup (Octopart/DigiKey) is v2, opt-in, behind the `Network` port. Local
  catalog (`docs/catalog_format.md`) is the supported path now.
- Dev Python is 3.14; installer target per PRD is bundled 3.12 (CI tests both).

## Next task: T35–T37 (triage, CSV Tier 2, Compare Runs)

Build as a new module folder `dfr/modules/m3_triage/` (copy `_example`), nothing outside it
except a screen folder and tests. Pieces:

1. **Triage engine (TRI-01..06)** — step `requires=["derating", "effective_stress", "parts"]`,
   `provides=["refinement"]`. Rank by `priority = severity x sensitivity x uncertainty` with
   the weights in a `data/triage/*.yaml` file (marked `verify`). Emit `RefinementItem`s
   (contract already exists in `dfr/core/contracts/v1/results.py`) and `ValuePrompt`s with
   `origin=M3` for parts whose verdict is WARN/UNKNOWN or within 10 % of a limit. Persist to
   an `m3_refinement_item` table on M3's migration branch.
2. **CSV Tier 2 import (OPC-03..06)** — service in M2 or M3: columns
   `refdes,param,stat,scenario,value,unit,source,tool,note`; validate refdes/param/unit,
   line-numbered diagnostics; writes `StressValue(tier=T2, source=measured|simulated)` rows;
   never deletes T1 rows (precedence resolver already handles it:
   `dfr/core/db/repos/stress.py::resolve_effective_stress`).
3. **Refinement queue screen** (`dfr/ui/screens/refine/`, step `refine`) — ranked list, answer
   prompt / import CSV / skip, "Re-run" button that calls `Workspace.run_tier1(parent_run_id=
   last run, tier_level=T2)` (add that parameter; `run_tier1` in `dfr/app/analysis.py` already
   accepts `parent_run_id` and `tier_level`).
4. **Compare Runs screen** — pick two runs of the version (`RunRepo.for_version`, `chain`);
   table of changed derating rows using `load_derating_results` (M5) and `load_thermal_results`
   (M6) services; the report already has a before/after section
   (`dfr/modules/m11_report/sections.py::render_refinement`) to reuse for the data shape.
5. Workflow state machine in `ShellViewModel`/`Workspace` currently stops at `analyze` DONE;
   wire `T2_QUEUED → T2_AWAITING_INPUT → RERUN → TRIAGED → FINAL` through `StepStatus`.

Patterns to follow (all have examples in the repo): module-owned tables + migration branch
(`m5_derating`), result loading services (`load_derating_results`), screen folder discovery
(`dfr/ui/screens/results/screen.py`), Qt-free view-model state (`dfr/ui/viewmodels/workspace.py`),
GUI flow test (`tests/ui/test_screens_gui.py`).

## Known gaps / small follow-ups

- `Results` screen: the MarginBar column (last column) is often scrolled out of view; give it
  a fixed width or move it next to Status.
- `example_catalog.json` has placeholder values (`i_sat: 0.0`) marked verify; the owner
  will replace them from datasheets. The missing-data report lists 15 Design C parts.
- Pin-map library has no seed entries for common 3-pin packages; `NET-06` prompts cover it.
- Inno Setup is not installed on the dev machine; `scripts/build_installer.py --skip-inno`
  was verified, the `.iss` script was not compiled.
- `requirements-lock.txt` is regenerated with `pip freeze --exclude-editable`; refresh after
  dependency changes.
- Do not run `ruff format` blindly on a file right after editing it with text replacement: it
  may change the anchor text you are about to replace next (bit us twice this session).

## Owner's environment notes

- Repo lives in OneDrive; `.venv` (1.1 GB) syncs unless excluded. Everything installed is
  inside `.venv`; nothing system-wide, no git hooks installed.
- Build artifacts `build/` and `dist/` (~1 GB) are git-ignored; delete after a packaging check.
