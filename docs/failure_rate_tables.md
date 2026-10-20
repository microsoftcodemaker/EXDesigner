# Failure-rate tables (M8) — import format

M8 computes part and system failure rates from **data files only**. The shipped
`data/models/failure_rate/mil_hdbk_217f.yaml` and `sr_332.yaml` have an **empty `classes` map**
(owner decision: handbook values are never transcribed from memory; SR-332 is licensed). Until a
filled table is present, every part is excluded with the reason "no table entry" and the system
rate reads *not available*. `pof.yaml` (Weibull shape factors) is shipped with seed values marked
`verify`.

Files live in `data/models/failure_rate/` (or `$DFR_DATA_DIR/models/failure_rate/` in the
installed app). Every `*.yaml` there is loaded; `RunConfig.failure_rate_method` selects one by
`id`, `None` runs every table that has data, each as its own result (constant-rate and wear-out
numbers are never summed together). All files are validated against
`data/schemas/failure_rate.schema.json`; an invalid file produces `FAILURE_RATE_TABLE_INVALID`
diagnostics and is skipped.

## Parts-stress table (`method: parts_stress`)

```yaml
id: mil_hdbk_217f            # ^[a-z][a-z0-9_]*$ ; selectable via failure_rate_method
method: parts_stress
version: 1
standard: "MIL-HDBK-217F Notice 2"
source: "where every number below came from (page/table)"
license: "redistribution terms"
confidence: low | medium | high
rate_unit: per_1e6_h | fit  # unit of lambda_b / c1 / c2; results are always in FIT
defaults:
  environment: GB            # key used by lookup factors with by: environment
  quality: commercial        # key used by lookup factors with by: quality
  kb_ev_per_k: 8.617e-5
classes:
  <part_class>:              # resistor | capacitor | inductor | diode | transistor | ic | connector | ...
    default:                 # used for any subtype not listed
      form: product          # lp = lambda_b * prod(pi)        (default)
      lambda_b: 0.0012
      factors: { ... }
    ceramic:                 # M1 subtype names, e.g. ceramic, aluminum_electrolytic, polymer, mosfet
      form: ic_sum           # lp = (c1 * piT + c2 * piE) * prod(other pi)   (217F microcircuits)
      c1: 0.01
      c2: 0.005
      factors: { ... }
```

Factor kinds (each becomes a named `pi*` entry in the result's `factors`):

| kind | fields | value |
| --- | --- | --- |
| `constant` | `value` | the constant |
| `lookup` | `by: quality` / `environment` / `attribute:<name>`, `table: {key: number}`, optional `default` | table row for the key (part attribute `quality` overrides the run default) |
| `arrhenius` | `ea_ev`, optional `t_ref_c` (25), `requires_tj` (false) | `exp[-(Ea/kB)(1/(T+273.15) - 1/(Tref+273.15))]` with T = worst-case Tj from M6, else Ta (stated in the assumptions; `requires_tj: true` excludes the part instead) |
| `stress_ratio` | `param` (stress name, e.g. `v_dc`), `rating` (rating name, e.g. `v_rated`), `curve: [[ratio, pi], ...]`, optional `log`, `default` | piecewise-linear interpolation of `max(stress)/rating`, clamped at the ends |
| `value_curve` | `curve: [[value_si, pi], ...]`, optional `log` (interpolate on log10 x), `default` | interpolation on the part value (F, H, ohm) |

A part whose factor input is missing (no stress, no rating, no table row, no Tj when required)
is **excluded with a reason**, never rated with a guess. Run-level keys are overridden with
`RunConfig.extra["fr_environment"]` / `["fr_quality"]`.

Series roll-up: `lambda_sys = sum(lambda_i)` FIT, `MTBF = 1e9 / lambda_sys` h, `R(t) = exp(-lambda t)`.

## PoF Weibull table (`method: pof_weibull`)

```yaml
id: pof
method: pof_weibull
version: 1
source: "..."
confidence: low
life_is: eta           # how an M7 life is read: eta (63.2 % failed) or b10
default_beta: 2.0
mechanisms:            # keyed by M7 LifetimeResult.mechanism
  electrolyte_dry_out: { beta: 3.0, source: "..." }
grid: { t_min_h: 1.0, points: 400 }
```

`R_i(t) = exp[-(t/eta_i)^beta_i]`, `R_sys = prod R_i`, MTTF by trapezoid on the log grid, B10 at
`R_sys = 0.9`. No MTBF is reported for this method (MTB-04). Per-part `lambda_fit` is the
*average hazard over the target life*, `-ln R_i(T_target)/T_target`, labelled in `factors`.

## Checking a file

```
python -c "from pathlib import Path; from dfr.modules.m8_failure_rate.tables import load_table_file as l; t=l(Path('my_table.yaml')); print(t.version, [d.message for d in t.diagnostics])"
```

`version == 0` means the file was rejected; the messages carry the JSON pointer of each error.
