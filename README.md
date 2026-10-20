# EXDesigner — Design for Reliability Toolkit

Offline Windows desktop tool that turns a CAD BOM and netlist into a ranked reliability risk
report for power electronics: derating, junction temperature, lifetime, and failure rate, with
every number labelled by source and fidelity tier. See the PRD for scope; this repository is
built milestone by milestone from it.

**Status:** MVP complete (PRD T01–T25) plus v1 slices T35–T37 and T29–T31: BOM/netlist
import, buck topology recognition with confirmation, Tier 1 equations, derating, thermal,
lifetime models (M7: electrolytic/polymer temperature rule, MLCC Prokopowicz–Vaskas,
Coffin–Manson + Miner thermal cycling, connector mating; constants in `data/models/lifetime`,
all `verify`; missing vendor data → "not available"), risk triage (M3: F0–F4 flags, PRD 3.3
ranking, waivers, Tier 2 prompts), Tier 2 CSV import, re-runs with parent links, Compare
Runs, immutable runs, HTML/PDF report, and an Altium-style PySide6 desktop app. Formats:
Altium `.BomDoc` + Protel netlist. Packaging: `python scripts/build_installer.py` (PyInstaller
one-folder; Inno Setup script in `packaging/`, needs ISCC installed). Not yet: failure rate
(M8), other topologies, FMEA (M9), lifetime rows in the Results screen/report.

## Quick start (development)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,gui]"
.venv\Scripts\pytest
.venv\Scripts\python -m dfr gui            # desktop app (dark Altium-style shell)
.venv\Scripts\python -m dfr analyze --bom tests/fixtures/design_c/design_c.BomDoc `
    --netlist tests/fixtures/design_c/design_c_protel.net --topology buck_integrated `
    --vin-min 7 --vin-max 22 --vout 3.3 --iout 3.25 --fsw 400e3 --ta 20
```

Python 3.12+ (tested on 3.12 and 3.14). Set `PYTHONUTF8=1` on Windows consoles so unit symbols
print correctly.

## Verification

| Check | Command |
| --- | --- |
| Lint / format | `ruff check .` and `ruff format --check .` |
| Types (strict on core, app, modules, topologies) | `mypy` |
| Layer rules (MOD-01) | `lint-imports` |
| Tests + coverage gate 85% | `pytest --cov` |
| Suite with each optional module deleted (MOD-03) | `python scripts/subtractive_test.py` |
| No hard-coded colors in UI (MOD-08) | `python scripts/check_ui_tokens.py` |
| File-size guideline | `python scripts/check_file_size.py` |

CI (`.github/workflows/ci.yml`) runs all of these on Windows, plus a job with PySide6 absent.

## Part catalog

Ratings and pinouts you collect from datasheets go in a local, per-MPN catalog (JSON or CSV,
imported in datasets that can be re-imported or deleted). Format and the rating vocabulary:
`docs/catalog_format.md`; example: `data/catalog/example_catalog.json`;
CLI: `python -m dfr catalog import|export|list|delete|missing`.

## Layout

```
dfr/core/        contracts (versioned pydantic), units, diagnostics, ports, registry, db
dfr/api/         public surface for module and plugin authors
dfr/app/         orchestrator (builds the pipeline from the registry; imports no module)
dfr/modules/     one folder per module: module.py + logic + migrations/   (_example is a stub)
dfr/topologies/  one folder per topology: pattern + template + data
dfr/ui/          PySide6 GUI (optional extra `gui`): shell/, kit/, viewmodels/ (Qt-free),
                 screens/<id>/screen.py discovered by folder; tokens.py holds every color
data/            rule sets, model constants, pin maps, FMEA library (data, not code)
tests/           pytest; tests/fixtures/design_c holds the supplied Altium netlist + BomDoc
docs/            architecture notes and how-to recipes
```

Read `docs/architecture.md` for how modules, topologies, screens and report sections plug in,
and `AGENTS.md` for the rules every change must follow.

## License

MIT. No MIL-HDBK-217F or Telcordia SR-332 tables are committed until their licensing is
verified (PRD A5, R3).
