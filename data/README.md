# Datasets — ATRIA (AIC 2026, Round 2, Track 2)

**No dataset is included in this repository.** All three are gitignored: they
are freely re-fetchable from the sources below, and not redistributing them
avoids any licence question. This file records what was used, where it came
from, and what it was used for.

Run `make status` to see which are present on your machine. The application
runs without any of them — the trained model is committed as a frozen artifact,
and the demo board uses the synthetic generator.

Three open datasets, downloaded 2026-08-21. None requires credentialing, a data
use agreement, or anyone's approval. All carry licence obligations — read the
Attribution section before publishing anything.

The MIMIC-IV-ED demo is distributed under the **Open Database License (ODbL)
v1.0** and the PhysioNet open-data terms; its licence text ships with the
download rather than being copied here, since the data itself is not in this
repository.

---

## `yale/` — Yale ED admission prediction dataset  ★ PRIMARY

| | |
|---|---|
| Source | [github.com/yaleemmlc/admissionprediction](https://github.com/yaleemmlc/admissionprediction) |
| Paper | Hong WS, Haimovich AD, Taylor RA (2018) PLOS ONE 13(7):e0201016 |
| Licence | Open — **citing the paper is a stated condition of use** |
| Period | March 2014 – July 2017, three hospitals |

| File | Size | Contents |
|---|---|---|
| `5v_cleandf.RData` | 103 MB | 560,486 visits x 972 variables, 202,953 unique patients |

### Why this is the primary source

The only open dataset carrying all four things Layer 1 needs at once:
nurse-assigned `esi`, seven `triage_vital_*` fields, a binary admission
outcome, **and** `race` / `ethnicity` / `lang` / `insurance_status` for a real
fairness audit. `dep_name` (3 hospitals) gives a free cross-site
generalisation test.

Published benchmarks on this exact data: **AUC 0.87** from triage variables
only (LR, XGBoost and DNN all), **0.92** with full patient history.
Overall admission rate 29.7%.

### Extraction — needs R, not pandas

The RData expands to ~3.9 GB. `pyreadr` was OOM-killed at an 11 GB cap on this
machine. Use R:

```bash
sudo apt install r-base
Rscript extract_yale.R    # writes a ~30-column slim CSV
```

### Two cautions

- **The paper's variable table has `hr` / `sbp` / `dbp` descriptions rotated by
  one row** (`triage_vital_hr` is described as "systolic blood pressure").
  Trust column names, and sanity-check value ranges before building features.
- Outcome is **admission**, not ICU-transfer-or-death. Coarser acuity proxy.
  Secondary high-acuity label: `esi in {1,2} AND admitted`.

---

## `isfahan/` — Emergency department admissions, Isfahan, Iran

| | |
|---|---|
| Source | [Mendeley Data, doi:10.17632/vhzyyktrz5.1](https://data.mendeley.com/datasets/vhzyyktrz5/1) |
| Paper | [Data in Brief, Oct 2024](https://www.sciencedirect.com/science/article/pii/S2352340924007911) · PMID 39257683 |
| Licence | **CC BY 4.0** — free to use and adapt, attribution required |
| Period | March 2017 – March 2022 |

| File | Rows | Cols |
|---|---|---|
| `ED_triage.csv` | 143,582 | 28 |
| `ED_admission.csv` | 143,280 | 26 |
| `Tables_Descriptions.docx` | — | partial data dictionary |

Join key: `triage_code` — **not unique**. 442 triage rows and 98 admission
rows share codes across different `PatientCode`s; the loader drops these as
genuinely ambiguous, leaving 143,140 stays.

### What it's for

Generator priors (age, complaint mix) from a non-Western health system — and a
data-quality case study worth a slide. **Do NOT train Layer 1 on it.** See the
leakage warning below.

### Measured missingness at triage

| Field | Missing |
|---|---|
| `Temperature` | 99.9% |
| `BlooddpressurSystol` | 82.8% |
| `BlooddpressurDiastol` | 82.6% |
| `RespiratoryRate` | 76.7% |
| `PulseRate` | 75.5% |
| `O2Saturation` | 73.8% |
| `AVPU` | 63.1% |
| `PainGrade` | 7.2% |

### Target leakage — do not train on this

Missingness encodes the triage decision itself, not clinical noise.
Counted over the six contract vitals (temperature, heartrate, resprate,
o2sat, sbp, dbp) after dropping ambiguous join keys — reproduce with
`data.loaders.isfahan.missingness_report`:

| TriageGrade | Patients | Mean vitals recorded /6 | Zero vitals |
|---|---|---|---|
| 1 (most urgent) | 10,267 | 0.00 | **100.0%** |
| 2 | 80,824 | 0.15 | **95.9%** |
| 3 | 34,322 | 4.14 | **0.1%** |
| 4 | 17,711 | 0.07 | **98.1%** |
| 5 | 16 | 0.00 | **100.0%** |

The sickest patients bypass the triage form entirely. A model using missing
indicators would score near-perfectly by learning hospital workflow rather than
physiology. The leak reaches the label too: zero-vitals patients have a 9.2%
outcome-code rate vs 0.4–2.8% for everyone else.

Also note: 56.5% of patients are graded 2, and grade 5 is used 19 times in
143,582 encounters — a triage scale collapsed toward the middle-high band.

### Other limitations

- **No repeated-vitals table.** One row per stay. Layer 2 cannot be trained or
  validated here.
- **`StatusOnDischarge` is not decoded** by the bundled docx (which only defines
  `kindref`, `explainer_id`, `accompainerRelation_id`). 11 codes, steeply graded
  by acuity — 36.1% of TriageGrade 1 vs 0.1% of TriageGrade 4 receive code 3.
  Get the meanings from the Data in Brief paper. Fallback label:
  `DischargeFromED` (binary, ~50/50) plus `ResidentDay` as severity proxy.
- **No race/ethnicity field.** Fairness audit is limited to sex and age band.
- Dates are split across `*_year` / `*_month` / `*_day` / `*_hour` columns.

---

## `mimic_ed_demo/` — MIMIC-IV-ED Demo v2.2

| | |
|---|---|
| Source | [PhysioNet](https://physionet.org/content/mimic-iv-ed-demo/2.2/) |
| Licence | **ODbL v1.0** (Open Database License) — attribution **and share-alike** |
| Origin | Beth Israel Deaconess Medical Center, Boston |

| File | Rows | Cols |
|---|---|---|
| `edstays.csv` | 222 | 9 |
| `triage.csv` | 222 | 11 |
| `vitalsign.csv` | 1,038 | 11 |
| `diagnosis.csv` | 545 | 6 |
| `medrecon.csv` | 2,764 | 9 |
| `pyxis.csv` | 1,082 | 7 |

### What it's for

**Schema truth** — identical column names to the full 425k credentialed set, so
the loader written against this works unchanged if full access lands.

**Layer 2 trajectories** — 159 stays carry ≥3 repeated `vitalsign` readings at
roughly 15-minute intervals. This is the only real deterioration data in the
project, and its open licence means these records may appear on screen and in
the demo video.

Dispositions: 150 admitted, 60 home, 5 transfer, plus 7 other/left.

### Parsing note

`triage.chiefcomplaint` contains unescaped commas inside quoted fields. Use a
real CSV parser — `split(",")` will corrupt the row.

---

## Attribution — required, do this on a slide

**Yale (Hong et al. 2018)** — "All research using this dataset should cite the
original paper." Cite: Hong WS, Haimovich AD, Taylor RA (2018) Predicting
hospital admission at emergency department triage using machine learning.
PLoS ONE 13(7): e0201016.

**Isfahan (CC BY 4.0)** — credit the authors of the Data in Brief 2024 paper and
link the Mendeley DOI. Attribution is a licence condition, not a courtesy.

**MIMIC-IV-ED Demo (ODbL v1.0)** — attribution required, **and share-alike**:
if you publicly distribute a database derived from it, that derived database
must also be offered under ODbL. Presenting metrics and figures is fine.
Publishing a processed copy of the data means licensing it ODbL.

Note this is stricter than ODC-BY. Do not redistribute a derived extract without
reading the terms in `mimic_ed_demo/LICENSE.txt`.

---

## Integrity

`ED_triage.csv` sha256 begins `a732dea0e1113969` — matches the hash published by
Mendeley. Re-verify with `sha256sum` if you re-download.

---

## Yale extraction — done

`yale_triage_slim.csv` — 560,486 rows x 24 columns, extracted with
`make extract-yale`. Layer 1 trains on it.

**The vitals are not rotated.** The check in the extraction script came back
clean: HR median 84, SBP 131, DBP 80, RR 18, SpO2 98, temp 98.0 — all
physiologically right, so the column names can be trusted despite the paper's
variable table describing them one row out.

Confirmed against the paper: admission rate 29.7%, three hospitals
(A 322,283 / B 166,497 / C 71,706), ESI 1-5 present with 2,457 missing.

Two properties of this dataset that matter downstream:

- **No pain score** in the slim extract, and it is an **adults-only** study, so
  `is_paediatric` is constant zero. Both features are dropped at fit time and
  recorded in `metrics["features_dropped"]`. Paediatric cases come from the
  synthetic generator, which is why that generator exists.
- **`disposition` is the strings `Admit` / `Discharge`**, not 0/1. Coercing to
  numeric silently yields an all-zero label and a model that trains happily on
  nothing.

### If you need to re-extract

Requires R. On Linux Mint 22.x the CRAN repo line must point at `noble`, not
`jammy` — Mint 22 is built on Ubuntu 24.04, and the jammy packages depend on
`libicu70`/`libtiff5` which do not exist there:

```bash
sudo sed -i 's|ubuntu jammy-cran40/|ubuntu noble-cran40/|' /etc/apt/sources.list
sudo apt update && sudo apt install r-base
make extract-yale
```

Alternatives if R will not install:

1. **R (recommended, ~2 min)** — `sudo apt install r-base` then
   `Rscript data/yale/extract_yale.R`. Needs your sudo password.
2. **Google Colab** — R and ~12 GB RAM are preinstalled and free. Upload the
   RData, run the same script, download `yale_triage_slim.csv`.

A pure-Python streaming parser was attempted and abandoned: R's XDR
serialisation nests attribute pairlists and string reference tables in ways that
desynchronise a hand-written reader after the second factor column. Not worth
more time when R does it correctly in one line.
