# Measured results

Generated 2026-08-22 by `make report`. Every figure below comes from a script in `eval/`; none is typed by hand.


## Layer 1 — acuity scorer

| metric | value |
|---|---|
| AUC | 0.8205 |
| sensitivity at operating point | 95.2% |
| specificity at that point | 22.6% |
| undertriage rate | 4.8% |
| outcome prevalence | 15.0% |
| train / calibrate / test | 2940 / 1260 / 1800 |

Operating point tuned to 95% sensitivity, matching the ACS <=5% undertriage standard, rather than to accuracy. Specificity is the price and is reported.


## Confidence — Mondrian conformal coverage

| class | empirical coverage |
|---|---|
| class_0 | 95.4% |
| class_1 | 97.4% |

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

| attribute   | group      |    n |   prevalence |   sensitivity |   false_alarm_rate |   undertriage |
|:------------|:-----------|-----:|-------------:|--------------:|-------------------:|--------------:|
| age_band    | adult      | 2804 |       0.0942 |        0.9848 |             0.8717 |        0.0152 |
| age_band    | geriatric  | 1908 |       0.0608 |        0.819  |             0.558  |        0.181  |
| age_band    | paediatric | 1288 |       0.4022 |        1      |             0.9558 |        0      |
| sex         | F          | 2997 |       0.1575 |        0.9725 |             0.7778 |        0.0275 |
| sex         | M          | 3003 |       0.1419 |        0.9718 |             0.7707 |        0.0282 |

### Equalised-odds gaps

| attribute   |   tpr_gap |   fpr_gap |   equalised_odds_diff | worst_served                  | within_tolerance   |
|:------------|----------:|----------:|----------------------:|:------------------------------|:-------------------|
| age_band    |    0.181  |    0.3978 |                0.3978 | geriatric (81.9% sensitivity) | False              |
| sex         |    0.0007 |    0.0071 |                0.0071 | M (97.2% sensitivity)         | True               |

### Mitigation — subgroup-conditional conformal (age_band)

| group      |    n |   sensitivity_before |   sensitivity_after |   false_alarm_before |   false_alarm_after |   threshold |
|:-----------|-----:|---------------------:|--------------------:|---------------------:|--------------------:|------------:|
| adult      | 2804 |               0.9848 |              0.9508 |               0.8717 |              0.7323 |     0.01356 |
| geriatric  | 1908 |               0.819  |              0.9569 |               0.558  |              0.8811 |     0.00128 |
| paediatric | 1288 |               1      |              0.9517 |               0.9558 |              0.3571 |     0.08821 |

**TPR gap 18.1% -> 0.6%.** Each group gets its own coverage guarantee rather than a shared average that hides the worst-served group inside it.


## Latency

| path | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| arrival (3x surge) | 120 | 25.69 | 45.62 | 60.28 | 65.09 | 
| vitals (3x surge) | 919 | 5.06 | 12.08 | 13.87 | 16.36 | 

All milliseconds. Budget is 400 ms, the figure already on the solution slide.


## Generalisation

_cross-source fallback (Yale not yet extracted)_

| key | value |
|---|---|
| trained_on | synthetic (n=3000, priors from Isfahan) |
| evaluated_on | mimic_demo (n=222 stays) |
| auc_in_domain | 0.8356 |
| auc_out_of_domain | 0.5677 |
| drop | 0.2679 |
| caveat | the label also changes: synthetic scores physiological deterioration, MIMIC scores admission. This drop mixes domain shift with label shift and is an upper bound on the former. Yale's dep_name split is the clean test. |

## The missingness audit

Blanking each vital and measuring the shift in predicted risk. Fields marked unsafe are clamped at score time so a missing vital can never score better than the population median.

| field       |   baseline_risk |   risk_when_missing |   delta | direction   | safe   |
|:------------|----------------:|--------------------:|--------:|:------------|:-------|
| temperature |          0.1416 |              0.1367 | -0.0049 | LOWERS RISK | False  |
| heartrate   |          0.1416 |              0.1411 | -0.0005 | LOWERS RISK | False  |
| resprate    |          0.1416 |              0.1379 | -0.0037 | LOWERS RISK | False  |
| o2sat       |          0.1416 |              0.1428 |  0.0011 | raises risk | True   |
| sbp         |          0.1416 |              0.1209 | -0.0208 | LOWERS RISK | False  |
| dbp         |          0.1416 |              0.1402 | -0.0015 | LOWERS RISK | False  |

Unsafe fields found: `temperature, heartrate, resprate, sbp, dbp`


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
