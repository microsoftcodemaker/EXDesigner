# Part catalog: file format and rating vocabulary

The catalog is the local, user-maintained store of part ratings and pinouts, keyed by MPN.
It is consulted after the BOM description text and before seed class defaults, and it wins
over both. Nothing in it is fetched from the internet; you build it from datasheets as you go,
and the same MPN is never asked for twice.

- Import: Catalog screen → Import, or `python -m dfr catalog import <file> [--dataset NAME]`
- Export: Catalog screen → Export, or `python -m dfr catalog export [--dataset NAME] > file.json`
- Delete a set: Catalog screen → Delete dataset, or `python -m dfr catalog delete NAME`
- Datasets: every file is one *dataset*. Importing a file whose `dataset` name already exists
  **replaces** that set (safe re-import after editing). Rows created from the app's own dialogs
  (Part Review → Edit rating, Circuit Review → pinout) live in dataset `user`.

Schema: `data/schemas/catalog.schema.json`. Example: `data/catalog/example_catalog.json`.

## JSON format

```json
{
  "format_version": 1,
  "dataset": "my-power-parts",
  "description": "optional free text",
  "verify": false,
  "parts": {
    "SPM6530T-100M-HZ": {
      "class": "inductor",
      "subtype": "power",
      "ratings": {
        "i_sat":   { "value": 5.2,  "unit": "A",    "source": "TDK SPM6530T datasheet p.3, 30 % inductance drop" },
        "i_rated": { "value": 4.2,  "unit": "A",    "source": "TDK SPM6530T datasheet p.3, 40 K temperature rise" },
        "dcr":     { "value": 0.08635, "unit": "ohm", "source": "TDK datasheet typ." }
      }
    },
    "LM63635CC3QDRRRQ1": {
      "class": "ic",
      "subtype": "switching_regulator",
      "ratings": {
        "v_in_max": { "value": 36, "unit": "V",   "source": "TI LM63635 datasheet, abs max VIN" },
        "theta_ja": { "value": 40, "unit": "K/W", "source": "TI datasheet thermal table, JEDEC 2s2p (verify)", "verify": true }
      },
      "pinmap": { "1": "vin", "2": "vin", "3": "gnd", "6": "boot", "7": "sw", "8": "vout_sense" }
    },
    "NMOS_GENERIC@SOT-23": {
      "class": "transistor",
      "subtype": "mosfet_n",
      "pinmap": { "1": "gate", "2": "source", "3": "drain" }
    }
  }
}
```

Rules:
- Key = MPN exactly as the BOM writes it (case and punctuation matter; spaces allowed). For a
  symbol without an MPN use `LIBREF@FOOTPRINT`.
- Every rating needs `value`, a pint-parsable `unit` (`V`, `A`, `ohm`, `W`, `F`, `H`, `degC`,
  `K/W`, `nC`, `s`, `uF`, `mohm`...; `""` for dimensionless like efficiency), and a `source`
  of at least 3 characters saying where the number came from. The source is shown in Part
  Review, in the Properties panel and in the report.
- `verify: true` on a rating (or on the whole file) appends "(verify)" to its source so it is
  shown low-confidence until checked.
- Values are stored as given; the app converts units internally (`"unit": "mohm"` is fine).

## CSV format (flat, one row per rating or per pin)

Columns (header row required, order free, `;` or `,` delimiter):

```
mpn,libref,footprint,class,subtype,rating,value,unit,source,pin,function
SPM6530T-100M-HZ,,,inductor,power,i_sat,5.2,A,TDK datasheet p.3,,
SPM6530T-100M-HZ,,,inductor,power,i_rated,4.2,A,TDK datasheet p.3,,
LM63635CC3QDRRRQ1,,,ic,switching_regulator,v_in_max,36,V,TI datasheet abs max,,
LM63635CC3QDRRRQ1,,,ic,switching_regulator,,,,,7,sw
LM63635CC3QDRRRQ1,,,ic,switching_regulator,,,,,6,boot
```

A row either carries a rating (`rating,value,unit,source`) or a pin (`pin,function`). The
dataset name is the file name without extension unless `--dataset` is given.

## Rating names the analysis understands

Use these exact names. Unknown names are stored and shown but no rule or model reads them.

| Class | Name | Unit | Used by |
| --- | --- | --- | --- |
| all | `t_max` | degC | resistor derating curve end point |
| capacitor | `v_rated` | V | derating `cap_*_voltage` |
| capacitor | `i_ripple` | A | derating `cap_elec_ripple` (electrolytic ripple rating at temperature) |
| capacitor | `esr` | ohm | M2 ESR_eq for output ripple voltage; lifetime (v1) |
| capacitor (electrolytic / polymer) | `l0_hours`, `t0_rated` | h, degC | M7 temperature rule (required; otherwise "not available") |
| capacitor (electrolytic / polymer) | `dt0_core` | K | M7 rated core rise; seed default used when absent (low confidence) |
| capacitor (MLCC) | `l1_hours`, `v1_test`, `t1_test` | h, V, degC | M7 Prokopowicz-Vaskas qualification point (required) |
| capacitor (MLCC, future) | `dc_bias_curve` (separate file) | — | DC-bias C_eff |
| connector | `mating_cycles` | "" | M7 connector life = rated / matings per year |
| resistor | `p_rated` | W | derating `res_power` |
| resistor | `t_knee` | degC | start of the power derating slope (typ. 70) |
| resistor | `v_rated` | V | derating `res_voltage` |
| inductor | `i_sat` | A | derating `ind_isat` (peak current) |
| inductor | `i_rated` | A | derating `ind_irms` (RMS / heating current) |
| inductor | `dcr` | ohm | M2 copper loss |
| transistor | `v_ds` | V | derating `fet_vds` |
| transistor | `i_d` | A | derating `fet_id` |
| transistor | `rds_on` | ohm | loss at 25 degC; M6 iterates Rds_on(Tj) |
| transistor | `qg`, `qrr`, `t_rise`, `t_fall`, `coss_eq`, `eoss` | C, C, s, s, F, J | switching/gate/reverse-recovery loss |
| transistor / diode / ic | `tj_max` | degC | derating `*_tj`, thermal runaway check |
| transistor / diode / ic | `theta_ja` | K/W | M6 Tj = Ta + P*theta_ja |
| transistor / diode / ic | `theta_jc`, `theta_cs`, `theta_sa` | K/W | M6 heatsink chain (used when theta_ja absent) |
| diode | `v_rated` | V | derating `diode_vr` (VRRM) |
| diode | `i_rated` | A | derating `diode_if` (IF(AV)) |
| diode | `vf`, `rd` | V, ohm | diode loss; asynchronous buck duty |
| ic (regulator) | `v_in_max` | V | derating `ic_vin` |
| ic (regulator) | `i_out` | A | derating `ic_iout` (rated output current) |
| ic (regulator) | `i_limit` | A | derating `ic_ilim` (peak switch current limit) |
| ic (regulator) | `rds_on_hs`, `rds_on_ls` | ohm | IC loss option 1 |
| ic (regulator) | `p_sw` | W | IC switching loss (option 1 add-on) |
| ic (regulator) | `eta` | "" | IC loss option 2 (efficiency at the operating point, 0-1) |

Pin functions: two-terminal passives need none. FETs: `gate`, `drain`, `source`. Diodes:
`anode`, `cathode`. Regulator ICs: `vin`, `sw`, `boot`, `vout_sense`, `fb`, `gnd`, `en`,
`pgood`, `other`.

## What happens on import

1. The file is validated (JSON Schema or CSV header/row checks). Any error aborts the import
   and is listed with a line number; nothing partial is written.
2. Rows of the same dataset are removed, then the file's entries are written with
   provenance `catalog` and the source text attached to each rating.
   There is one entry per MPN across all datasets: if another dataset already has the MPN,
   the new file's ratings and pins are merged over it (new wins per key) and the entry now
   belongs to the new dataset, so deleting a dataset removes the entries it last wrote.
3. Parts already imported in a design are **not** rewritten: ratings are looked up at BOM
   import time. Re-import the design (new version) to pick up catalog changes, or edit the
   part's ratings directly on Part Review.
