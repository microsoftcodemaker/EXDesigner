# Data files

Rule sets, model constants, pin maps and the FMEA library are **data, not code** (PRD 2.7
rule 6). Each file is validated against a JSON Schema in `schemas/` and every constant carries
a `source` citation. Values not yet checked against a primary source are marked `verify`.

| Folder | Contents | Arrives with |
| --- | --- | --- |
| `rulesets/` | derating rule sets (`generic_conservative`, `generic_commercial`, `space_reference`) | M5 |
| `triage/` | triage thresholds, ranking weights and the F4 blind-spot table (`default`) | M3 |
| `models/` | lifetime and failure-rate constants | M7, M8 |
| `pinmaps/` | pin-function maps keyed by MPN / LibRef + footprint | M1 |
| `fmea/` | failure-mode library by part class | M9 |
| `schemas/` | JSON Schemas for the above | with each |

Licensed material (Telcordia SR-332 tables) is never committed; users import their own.
