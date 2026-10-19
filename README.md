# EXDesigner — Design for Reliability Toolkit

Offline Windows desktop tool that turns a CAD BOM and netlist into a ranked reliability risk
report for power electronics: derating, junction temperature, lifetime, and failure rate, with
every number labelled by source and fidelity tier. See the PRD for scope; this repository is
built milestone by milestone from it.

**Status:** MVP feature-complete except packaging (PRD T01–T24). BOM/netlist import, buck
topology recognition with confirmation, Tier 1 equations, derating, thermal, immutable runs,
HTML/PDF report, and an Altium-style PySide6 desktop app (dark theme, dockable Project /
Properties / Messages panels, document tabs). Formats: Altium `.BomDoc` + Protel netlist.
Packaging: `python scripts/build_installer.py` (PyInstaller one-folder, ~535 MB unpacked; Inno Setup
script in `packaging/`, needs ISCC installed). Not yet: v1 modules (lifetime, failure rate, triage,
CSV Tier 2, FMEA).

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
