# Measured results

Generated 2026-08-27 by `make report`. Every figure below comes from a script in `eval/`; none is typed by hand.


## Layer 1 — acuity scorer

_Trained on: Yale ED, 560,486 real encounters across three hospitals (Hong et al. 2018)_

| metric | value |
|---|---|
| AUC | 0.8085 |
| sensitivity at operating point | 95.0% |
| specificity at that point | 34.1% |
| undertriage rate | 5.0% |
| outcome prevalence | 29.7% |
| train / calibrate / test | 274638 / 117702 / 168146 |

Operating point tuned to 95% sensitivity, matching the ACS <=5% undertriage standard, rather than to accuracy. Specificity is the price and is reported.


### Against the published benchmark

Hong et al. (2018) trained on these same 560,486 encounters and reported AUC 0.87 from triage variables alone, and 0.92 with full patient history across 972 variables.

| model | features | AUC |
|---|---|---|
| Hong et al., triage variables only | ~90 one-hot | 0.87 |
| **ATRIA**, PRD-compliant features | 23 | **0.8085** |
| Hong et al., full model with history | 972 | 0.92 |

ATRIA scores lower than the benchmark on purpose. The published model uses the nurse's own ESI level and demographic attributes including race; the PRD forbids both (14.2, 14.3). Adding the nurse's ESI back lifts us to 0.859 — so roughly 0.05 AUC is the measurable price of producing a recommendation that is genuinely independent of the nurse, and of refusing to use race as a predictive shortcut. That is a price worth naming rather than a gap worth hiding: a model that reads the nurse's answer cannot meaningfully disagree with it, and the blind-assessment workflow it feeds would be theatre.


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
| age_band    | adult                            | 392844 |       0.1992 |        0.9017 |             0.5928 |        0.0983 |
| age_band    | geriatric                        | 167642 |       0.5273 |        0.9949 |             0.9208 |        0.0051 |
| sex         | Female                           | 309653 |       0.2892 |        0.9472 |             0.6263 |        0.0528 |
| sex         | Male                             | 250833 |       0.3073 |        0.9557 |             0.7    |        0.0443 |
| race        | American Indian or Alaska Native |    515 |       0.301  |        0.9419 |             0.6778 |        0.0581 |
| race        | Asian                            |   5790 |       0.2321 |        0.9368 |             0.522  |        0.0632 |
| race        | Black or African American        | 157884 |       0.2377 |        0.9475 |             0.65   |        0.0525 |
| race        | Other                            |  89359 |       0.2057 |        0.908  |             0.6109 |        0.092  |
| race        | Patient Refused                  |   5203 |       0.2183 |        0.9261 |             0.6034 |        0.0739 |
| race        | Unknown                          |   1702 |       0.2086 |        0.9352 |             0.5865 |        0.0648 |
| race        | White or Caucasian               | 299632 |       0.3593 |        0.9603 |             0.6867 |        0.0397 |

### Equalised-odds gaps

| attribute   |   tpr_gap |   fpr_gap |   equalised_odds_diff | worst_served               | within_tolerance   |
|:------------|----------:|----------:|----------------------:|:---------------------------|:-------------------|
| age_band    |    0.0932 |    0.328  |                0.328  | adult (90.2% sensitivity)  | False              |
| race        |    0.0523 |    0.1647 |                0.1647 | Other (90.8% sensitivity)  | False              |
| sex         |    0.0085 |    0.0737 |                0.0737 | Female (94.7% sensitivity) | False              |

### Mitigation — subgroup-conditional conformal (race)

| group                                     |      n |   sensitivity_before |   sensitivity_after |   false_alarm_before |   false_alarm_after |   threshold |
|:------------------------------------------|-------:|---------------------:|--------------------:|---------------------:|--------------------:|------------:|
| American Indian or Alaska Native          |    515 |               0.9419 |              0.9548 |               0.6778 |              0.7056 |     0.1006  |
| Asian                                     |   5790 |               0.9368 |              0.9501 |               0.522  |              0.5668 |     0.09543 |
| Black or African American                 | 157884 |               0.9475 |              0.95   |               0.65   |              0.6592 |     0.10521 |
| Native Hawaiian or Other Pacific Islander |    375 |               0.9367 |              0.962  |               0.6723 |              0.8176 |     0.07554 |
| Other                                     |  89359 |               0.908  |              0.95   |               0.6109 |              0.7366 |     0.08207 |
| Patient Refused                           |   5203 |               0.9261 |              0.9507 |               0.6034 |              0.6821 |     0.09128 |
| Unknown                                   |   1702 |               0.9352 |              0.9521 |               0.5865 |              0.6548 |     0.09077 |
| White or Caucasian                        | 299632 |               0.9603 |              0.95   |               0.6867 |              0.6479 |     0.12038 |
| unknown                                   |     26 |               1      |              1      |               0.5789 |              0.3684 |     0.18673 |

**TPR gap 9.2% -> 5.0%.** Each group gets its own coverage guarantee rather than a shared average that hides the worst-served group inside it.


## Latency

| path | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| arrival (3x surge) | 120 | 25.31 | 53.1 | 94.83 | 107.23 | 
| vitals (3x surge) | 896 | 5.22 | 11.62 | 13.12 | 14.82 | 

All milliseconds. Budget is 400 ms, the figure already on the solution slide.


## Generalisation

_Yale three-hospital split_

| key | value |
|---|---|
| holdout_site | C |
| sites | ['A', 'B', 'C'] |
| auc_A | 0.8025 |
| n_A | 322283 |
| auc_B | 0.8255 |
| n_B | 166497 |
| auc_C | 0.7477 |
| n_C | 71706 |

## The missingness audit

Blanking each vital and measuring the shift in predicted risk. Fields marked unsafe are clamped at score time so a missing vital can never score better than the population median.

| field       |   baseline_risk |   risk_when_missing |   delta | direction   | safe   |
|:------------|----------------:|--------------------:|--------:|:------------|:-------|
| temperature |          0.2992 |              0.3287 |  0.0294 | raises risk | True   |
| heartrate   |          0.2992 |              0.3294 |  0.0302 | raises risk | True   |
| resprate    |          0.2992 |              0.3076 |  0.0084 | raises risk | True   |
| o2sat       |          0.2992 |              0.3041 |  0.0049 | raises risk | True   |
| sbp         |          0.2992 |              0.3135 |  0.0143 | raises risk | True   |
| dbp         |          0.2992 |              0.3175 |  0.0182 | raises risk | True   |

Unsafe fields found: `none`


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

- The outcome label is hospital **admission**, a coarser acuity proxy than ICU-transfer-or-death. No open ED dataset carries ICU timestamps; this is the first thing to fix with real hospital access.
- Yale is an **adults-only** study with no pain score, so `is_paediatric` and `pain` are dropped at fit time. Paediatric cases come from the synthetic generator, which is why that generator exists.
- Layer 2 is validated on 159 real trajectories — a small sample.
- Race is audited but never used as a model input (PRD 14.2). Fairness mitigation adjusts per-subgroup thresholds; it does not remove the underlying difference in how patients arrive.
- Every threshold here is a prototype default. None has been approved by a clinical governance body, and none should be used on a real patient.
