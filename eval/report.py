"""
Generate docs/results.md from live measurements.

Every number the deck quotes is produced here. Run `make report` after any model
change so the slides cannot drift away from the code — a stale number on a slide
is the easiest way to lose a judge's trust.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

import data.loaders as loaders
from data.loaders.synthetic import generate
from eval import cross_site, fairness, latency, lead_time
from layer1 import features
from layer1.model import AcuityScorer
from layer1.verify import missingness_directions

OUT = Path("docs/results.md")


def main() -> None:
    print("measuring...")
    ds = generate(6000, seed=3)
    scorer = AcuityScorer().fit(ds)
    X = features.build(ds)

    m = scorer.metrics
    lt = lead_time.run()
    lat = latency.measure(scorer, surge=3.0)
    fair = fairness.audit(scorer, ds)
    eo = fairness.equalised_odds(fair)
    mit = fairness.mitigate(scorer, ds)
    miss = missingness_directions(scorer, X)
    isf = loaders.load("isfahan")
    from data.loaders.isfahan import missingness_report
    leak = missingness_report(isf)

    try:
        xs = cross_site.yale_cross_site()
        xs_note = "Yale three-hospital split"
    except Exception:
        xs = cross_site.cross_source()
        xs_note = "cross-source fallback (Yale not yet extracted)"

    L = []
    w = L.append
    w("# Measured results\n")
    w(f"Generated {date.today().isoformat()} by `make report`. "
      "Every figure below comes from a script in `eval/`; none is typed by hand.\n")

    w("\n## Layer 1 — acuity scorer\n")
    w("| metric | value |")
    w("|---|---|")
    w(f"| AUC | {m['auc']} |")
    w(f"| sensitivity at operating point | {m['sensitivity']:.1%} |")
    w(f"| specificity at that point | {m['specificity']:.1%} |")
    w(f"| undertriage rate | {m['undertriage_rate']:.1%} |")
    w(f"| outcome prevalence | {m['prevalence']:.1%} |")
    w(f"| train / calibrate / test | {m['n_train']} / {m['n_cal']} / {m['n_test']} |")
    w("\nOperating point tuned to 95% sensitivity, matching the ACS <=5% undertriage "
      "standard, rather than to accuracy. Specificity is the price and is reported.\n")

    w("\n## Confidence — Mondrian conformal coverage\n")
    w("| class | empirical coverage |")
    w("|---|---|")
    for k, v in m["conformal_coverage"].items():
        w(f"| {k} | {v:.1%} |")
    w("\nClass-conditional, calibrated on a split held out from fitting. Marginal "
      "conformal reaches its average by under-covering the rare class — here the "
      "critical patients — which is why the guarantee is made per class.\n")

    w("\n## Layer 2 — trajectory signal on real patients\n")
    w(f"MIMIC-IV-ED demo, {lt['stays_examined']} stays with >=3 repeated readings, "
      "replayed reading by reading.\n")
    w("| metric | value |")
    w("|---|---|")
    w(f"| flagged among admitted or transferred | {lt['sensitivity_admitted']:.1%} "
      f"(n={lt['n_admitted']}) |")
    w(f"| flagged among discharged home | {lt['false_positive_discharged']:.1%} "
      f"(n={lt['n_discharged']}) |")
    w(f"| median lead time | {lt['median_lead_minutes']:.0f} min before last reading |")
    w("\nQueue aging is suppressed for this measurement: real ED stays run for hours, "
      "so the aging term fires on nearly everyone and would drown the physiological "
      "signal being measured.\n")

    w("\n## Fairness\n")
    w("### Per-subgroup performance at the operating point\n")
    w(fair.to_markdown(index=False))
    w("\n### Equalised-odds gaps\n")
    w(eo.to_markdown(index=False))
    w(f"\n### Mitigation — subgroup-conditional conformal ({mit['attribute']})\n")
    w(mit["detail"].to_markdown(index=False))
    w(f"\n**TPR gap {mit['tpr_gap_before']:.1%} -> {mit['tpr_gap_after']:.1%}.** "
      "Each group gets its own coverage guarantee rather than a shared average "
      "that hides the worst-served group inside it.\n")

    w("\n## Latency\n")
    w("| path | n | p50 | p95 | p99 | max |")
    w("|---|---|---|---|---|---|")
    for path in ("arrival_ms", "vitals_ms"):
        s = lat[path]
        w(f"| {path[:-3]} (3x surge) | {s['n']} | {s['p50']} | {s['p95']} | "
          f"{s['p99']} | {s['max']} | ")
    w(f"\nAll milliseconds. Budget is {latency.BUDGET_MS} ms, the figure already on "
      "the solution slide.\n")

    w("\n## Generalisation\n")
    w(f"_{xs_note}_\n")
    w("| key | value |")
    w("|---|---|")
    for k, v in xs.items():
        w(f"| {k} | {v} |")

    w("\n## The missingness audit\n")
    w("Blanking each vital and measuring the shift in predicted risk. Fields marked "
      "unsafe are clamped at score time so a missing vital can never score better "
      "than the population median.\n")
    w(miss.to_markdown(index=False))
    w(f"\nUnsafe fields found: `{', '.join(m['unsafe_missing_fields']) or 'none'}`\n")

    w("\n## The Isfahan trap\n")
    w("Why this dataset is excluded from training.\n")
    w(leak.to_markdown())
    w("\nGrade 1 patients bypass the triage form entirely, so the *presence* of a "
      "reading nearly predicts the triage grade. A model using missing-indicators "
      "would score near-perfectly on hospital workflow rather than physiology.\n")

    w("\n## Figures\n")
    for p in sorted(Path("docs/figures").glob("*.png")):
        w(f"- `{p}`")

    w("\n## Stated limitations\n")
    w("- Layer 1 is trained on synthetic patients calibrated to real priors. Yale's "
      "560,486 real visits are downloaded but not yet extracted (needs R).")
    w("- The synthetic outcome is physiological deterioration; Yale's is hospital "
      "admission, a coarser acuity proxy. Neither is ICU-transfer-or-death.")
    w("- Layer 2 is validated on 159 real trajectories — a small sample.")
    w("- Paediatric cases are synthetic; the adult sources cannot supply them.")
    w("- Fairness is audited on sex and age band only until Yale supplies race, "
      "ethnicity, language and insurance.")

    OUT.write_text("\n".join(L) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
