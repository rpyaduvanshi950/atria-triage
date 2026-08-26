# Measured results

Generated 2026-08-26 by `make report`. Every figure below comes from a script in `eval/`; none is typed by hand.


## Layer 1 — acuity scorer

_Trained on: Yale ED, 560,486 real encounters across three hospitals (Hong et al. 2018)_

| metric | value |
|---|---|
| AUC | 0.8588 |
| sensitivity at operating point | 95.0% |
| specificity at that point | 52.1% |
| undertriage rate | 5.0% |
| outcome prevalence | 29.7% |
| train / calibrate / test | 274638 / 117702 / 168146 |

Operating point tuned to 95% sensitivity, matching the ACS <=5% undertriage standard, rather than to accuracy. Specificity is the price and is reported.


### Against the published benchmark

Hong et al. (2018) trained on these same 560,486 encounters and reported AUC 0.87 from triage variables alone, and 0.92 with full patient history across 972 variables.

| model | features | AUC |
|---|---|---|
| Hong et al., triage variables only | ~90 one-hot | 0.87 |
| **ATRIA**, vitals + demographics + nurse ESI | 27 | **0.8588** |
| Hong et al., full model with history | 972 | 0.92 |

The nurse's own ESI level is worth roughly 0.04 AUC on its own: without it the same model reaches 0.820. That is a measure of how much of triage is human judgement rather than vital signs.


## Confidence — Mondrian conformal coverage

| class | empirical coverage |
|---|---|
| class_0 | 95.0% |
| class_1 | 95.0% |

Class-conditional, calibrated on a split held out from fitting. Marginal conformal reaches its average by under-covering the rare class — here the critical patients — which is why the guarantee is made per class.


## Layer 2 — trajectory signal on real patients

MIMIC-IV-ED demo, 159 stays with >=3 repeated readings, replayed reading by reading.

| metric | value |
|---|---|
| flagged among admitted or transferred | 32.2% (n=118) |
| flagged among discharged home | 12.2% (n=41) |
| median lead time | 164 min before last reading |

Queue aging is suppressed for this measurement: real ED stays run for hours, so the aging term fires on nearly everyone and would drown the physiological signal being measured.


## Fairness

### Per-subgroup performance at the operating point

| attribute   | group                            |      n |   prevalence |   sensitivity |   false_alarm_rate |   undertriage |
|:------------|:---------------------------------|-------:|-------------:|--------------:|-------------------:|--------------:|
| age_band    | adult                            | 392844 |       0.1992 |        0.9082 |             0.4155 |        0.0918 |
| age_band    | geriatric                        | 167642 |       0.5273 |        0.9905 |             0.7312 |        0.0095 |
| sex         | Female                           | 309653 |       0.2892 |        0.9465 |             0.4624 |        0.0535 |
| sex         | Male                             | 250833 |       0.3073 |        0.9581 |             0.5001 |        0.0419 |
| race        | American Indian or Alaska Native |    515 |       0.301  |        0.9548 |             0.55   |        0.0452 |
| race        | Asian                            |   5790 |       0.2321 |        0.9249 |             0.3587 |        0.0751 |
| race        | Black or African American        | 157884 |       0.2377 |        0.9366 |             0.4195 |        0.0634 |
| race        | Other                            |  89359 |       0.2057 |        0.8865 |             0.3833 |        0.1135 |
| race        | Patient Refused                  |   5203 |       0.2183 |        0.919  |             0.4    |        0.081  |
| race        | Unknown                          |   1702 |       0.2086 |        0.9155 |             0.3467 |        0.0845 |
| race        | White or Caucasian               | 299632 |       0.3593 |        0.9692 |             0.5571 |        0.0308 |

### Equalised-odds gaps

| attribute   |   tpr_gap |   fpr_gap |   equalised_odds_diff | worst_served               | within_tolerance   |
|:------------|----------:|----------:|----------------------:|:---------------------------|:-------------------|
| age_band    |    0.0823 |    0.3157 |                0.3157 | adult (90.8% sensitivity)  | False              |
| race        |    0.0827 |    0.2104 |                0.2104 | Other (88.6% sensitivity)  | False              |
| sex         |    0.0116 |    0.0377 |                0.0377 | Female (94.7% sensitivity) | True               |

### Mitigation — subgroup-conditional conformal (race)

| group                                     |      n |   sensitivity_before |   sensitivity_after |   false_alarm_before |   false_alarm_after |   threshold |
|:------------------------------------------|-------:|---------------------:|--------------------:|---------------------:|--------------------:|------------:|
| American Indian or Alaska Native          |    515 |               0.9548 |              0.9548 |               0.55   |              0.55   |     0.14625 |
| Asian                                     |   5790 |               0.9249 |              0.9501 |               0.3587 |              0.4037 |     0.11824 |
| Black or African American                 | 157884 |               0.9366 |              0.95   |               0.4195 |              0.4457 |     0.12861 |
| Native Hawaiian or Other Pacific Islander |    375 |               0.9241 |              0.962  |               0.4088 |              0.4324 |     0.13739 |
| Other                                     |  89359 |               0.8865 |              0.95   |               0.3833 |              0.5053 |     0.09249 |
| Patient Refused                           |   5203 |               0.919  |              0.9507 |               0.4    |              0.4655 |     0.11174 |
| Unknown                                   |   1702 |               0.9155 |              0.9521 |               0.3467 |              0.4039 |     0.11766 |
| White or Caucasian                        | 299632 |               0.9692 |              0.95   |               0.5571 |              0.5007 |     0.18093 |
| unknown                                   |     26 |               0.8571 |              1      |               0.3158 |              0.6842 |     0.03287 |

**TPR gap 11.2% -> 5.0%.** Each group gets its own coverage guarantee rather than a shared average that hides the worst-served group inside it.


## Latency

| path | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| arrival (3x surge) | 120 | 25.23 | 52.48 | 86.46 | 119.05 | 
| vitals (3x surge) | 896 | 4.91 | 12.53 | 14.07 | 16.29 | 

All milliseconds. Budget is 400 ms, the figure already on the solution slide.


## Generalisation

_Yale three-hospital split_

| key | value |
|---|---|
| holdout_site | C |
| sites | ['A', 'B', 'C'] |
| auc_A | 0.8498 |
| n_A | 322283 |
| auc_B | 0.8756 |
| n_B | 166497 |
| auc_C | 0.8344 |
| n_C | 71706 |

## The missingness audit

Blanking each vital and measuring the shift in predicted risk. Fields marked unsafe are clamped at score time so a missing vital can never score better than the population median.

| field       |   baseline_risk |   risk_when_missing |   delta | direction   | safe   |
|:------------|----------------:|--------------------:|--------:|:------------|:-------|
| temperature |          0.3014 |              0.3132 |  0.0118 | raises risk | True   |
| heartrate   |          0.3014 |              0.3188 |  0.0174 | raises risk | True   |
| resprate    |          0.3014 |              0.3077 |  0.0063 | raises risk | True   |
| o2sat       |          0.3014 |              0.3032 |  0.0018 | raises risk | True   |
| sbp         |          0.3014 |              0.2957 | -0.0057 | LOWERS RISK | False  |
| dbp         |          0.3014 |              0.3051 |  0.0037 | raises risk | True   |

Unsafe fields found: `sbp`


## The Isfahan trap

Why this dataset is excluded from training.

|   grade |   patients |   mean_recorded |   pct_zero_vitals |
|--------:|-----------:|----------------:|------------------:|
|       1 |      10267 |            0    |            100    |
|       2 |      80824 |            0.15 |             95.88 |
|       3 |      34322 |            4.14 |              0.08 |
|       4 |      17711 |            0.07 |             98.08 |
|       5 |         16 |            0    |            100    |

Grade 1 patients bypass the triage form entirely, so the *presence* of a reading nearly predicts the triage grade. A model using missing-indicators would score near-perfectly on hospital workflow rather than physiology.


## Figures

- `docs/figures/01-roc.png`
- `docs/figures/02-cost-curve.png`
- `docs/figures/03-fairness.png`
- `docs/figures/04-layer2-real.png`
- `docs/figures/05-isfahan-leakage.png`

## Stated limitations

- Layer 1 is trained on synthetic patients calibrated to real priors. Yale's 560,486 real visits are downloaded but not yet extracted (needs R).
- The synthetic outcome is physiological deterioration; Yale's is hospital admission, a coarser acuity proxy. Neither is ICU-transfer-or-death.
- Layer 2 is validated on 159 real trajectories — a small sample.
- Paediatric cases are synthetic; the adult sources cannot supply them.
- Fairness is audited on sex and age band only until Yale supplies race, ethnicity, language and insurance.
