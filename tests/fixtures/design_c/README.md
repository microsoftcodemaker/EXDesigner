# Design C fixtures: integrated-switch buck (supplied board)

Source: user-supplied Altium exports of the SPRW power board (LM63635 fixed 3.3 V buck,
INA238 current monitors, input P-FET switch). Do not edit; parsers are tested against these
bytes. Keep CRLF line endings (`.gitattributes` marks them binary-ish).

## `design_c_protel.net` — Altium netlist, Protel text format

- ASCII, CRLF. 28 component blocks, 19 net blocks.
- Component block: `[` / refdes / footprint / comment (= MPN) / three blank lines / `]`.
- Net block: `(` / net name / `REF-PIN` lines / `)`. Split `REF-PIN` at the **last** hyphen.
- Net `SCL` is empty (no pins). U3 (LM63635, 12-WFDFN + pad) uses pins 1–11 and 13.
- Pin numbers only; no pin names/types. Pin functions come from the pin-map library or user.
- Comment field holds the MPN, not a value, e.g. `Copy of MHDR1X3` (MPN with spaces).

Expected `buck_integrated` role map (golden, PRD section 3.12 and REC-10):

| Rail | Net |
| --- | --- |
| `vin` | `Buck_in` (C1-2, C2-2, U3-1, U3-2) |
| `sw` | `NetC3_1` (C3-1, L1-1, U3-7) |
| `vout` | `Buck_out` (C5-2, C6-2, L1-2, U3-8, R3-1) |
| `gnd` | `GND` |

| Role | Refdes |
| --- | --- |
| `ic` | U3 |
| `inductor` | L1 |
| `output_cap` | C5, C6 |
| `input_cap` | C1, C2 |
| `boot_cap` | C3 (NetC3_2 = U3-6) |
| `other` | everything else (R3 shunt, U1/U2 INA238, Q1, Q2, D1-D3, F1, J1, J2, P1, R1-R7, C4, C7, C8) |

Inferred IC pin functions (prefill only, must be user-confirmed): `sw`=7, `boot`=6,
`vin`=1,2, `vout_sense`=8, `gnd`=3,5,11,13, `en/reset`=9 (net `RESET_N`), `vcc`=4,10.

## Operating point (board owner, PRD 8.2 Design C)

Vin 7–22 V, Vout 3.3 V (fixed), Iout_max 3.25 A, fsw 400 kHz, ambient 20 °C. Expected Tier 1
verdicts with `generic_conservative`: C2 (35 V X7R) WARN at 22 V, C1 (50 V) PASS, U3 `i_out`
WARN at 100 % of rating, L1 `i_sat` UNKNOWN (no rating), IC loss prompted.

## `design_c.BomDoc` — Altium LiveBOM

- Latin-1, CRLF, pipe-delimited `|KEY=VALUE` records, one record per line.
- 22 `RECORD=CatalogItem` lines: `DESCRIPTION` (parsable value/rating text) and
  `USERCOMMENTS` (= MPN, the join key to the netlist comment field). No designators.
- Many `RECORD=PartChoice` lines with supplier data and datasheet URLs: store as links,
  never fetch (PRD BOM-10 off by default).
- Join: 28 netlist components → 22 MPNs, 0 unmatched expected (NET-10).

Descriptions that the value/rating parser (T05) must handle:

```
CAP CER 0.22UF 50V X7R 0805
CAP CER 22UF 10V X7R 1210
FIXED IND 10UH 4.2A 86.35MOHM SM
RES SMD 88.7K OHM 1% 1/10W 0603
RES SHUNT, 2512, 0.015 OHM, 1%,
DIODE ZENER 10V 200MW SOD323
Single P-Channel 30 V 4.1 mOhm 125 nC OptiMOS? Power Mosfet - TO-252-3-11
Buck Switching Regulator IC Positive Fixed 3.3V 1 Output 3.25A 12-WFDFN Exposed Pad
```
