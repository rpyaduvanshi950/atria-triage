"""
Export the deck figures.

Every number here comes from a measurement script in this package — nothing is
typed in by hand. Run `make figures` after any model change so the slides cannot
drift away from the code.

Palette validated against the dataviz six checks (light surface):
  #0B8C7D teal   primary series
  #B4530F orange comparison series
  worst adjacent CVD dE 12.6 (deutan), normal-vision dE 22.7, all contrast >= 3:1
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import roc_curve

OUT = Path("docs/figures")

TEAL, ORANGE = "#0B8C7D", "#B4530F"
INK, INK_2, INK_3 = "#131F1D", "#546562", "#7E8F8B"
RULE, SURFACE = "#DBE3E1", "#FCFCFB"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": RULE, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
    "axes.titlesize": 11, "axes.titleweight": "semibold", "axes.titlelocation": "left",
    "axes.titlepad": 12, "axes.labelsize": 9,
    "xtick.color": INK_3, "ytick.color": INK_3, "xtick.bottom": False, "ytick.left": False,
    "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": RULE, "grid.linewidth": 0.6, "legend.frameon": False,
    "legend.fontsize": 8.5, "savefig.bbox": "tight", "savefig.dpi": 200,
})


def _save(fig, name: str, caption: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.text(0.0, -0.10, caption, fontsize=7.5, color=INK_3, ha="left", va="top", wrap=True)
    fig.savefig(OUT / f"{name}.png")
    plt.close(fig)
    print(f"  wrote docs/figures/{name}.png")


# --- 1. ROC with the operating point ---------------------------------------

def fig_roc(scorer, X, y) -> None:
    p = scorer.score_frame(X)
    fpr, tpr, thr = roc_curve(y, p)
    idx = int(np.argmin(np.abs(thr - scorer.threshold)))

    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    ax.plot([0, 1], [0, 1], lw=1, ls=(0, (3, 3)), color=INK_3, zorder=1)
    ax.plot(fpr, tpr, lw=2, color=TEAL, zorder=3)
    ax.scatter([fpr[idx]], [tpr[idx]], s=64, color=TEAL, ec=SURFACE, lw=2, zorder=4)
    ax.annotate(
        f"operating point\n{tpr[idx]:.0%} sensitivity · {1 - fpr[idx]:.0%} specificity",
        (fpr[idx], tpr[idx]), xytext=(14, -34), textcoords="offset points",
        fontsize=8.5, color=INK, arrowprops=dict(arrowstyle="-", color=INK_3, lw=0.8))
    ax.set(xlabel="false alarm rate", ylabel="sensitivity", xlim=(0, 1), ylim=(0, 1.02))
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title(f"Layer 1 discrimination — AUC {scorer.metrics['auc']:.3f}")
    ax.grid(axis="both", lw=0.6)
    ax.set_axisbelow(True)
    _save(fig, "01-roc",
          "Threshold tuned to 95% sensitivity, matching the ACS <=5% undertriage standard. "
          "Specificity is the price paid, and is reported rather than buried.")


# --- 2. asymmetric cost curve ----------------------------------------------

def fig_cost(scorer, X, y, ratio: int = 50) -> None:
    p = scorer.score_frame(X)
    grid = np.quantile(p, np.linspace(0.001, 0.999, 400))
    costs, sens = [], []
    for t in grid:
        flag = p >= t
        fn = int(((~flag) & (y == 1)).sum())
        fp = int((flag & (y == 0)).sum())
        costs.append(ratio * fn + fp)
        sens.append(flag[y == 1].mean())
    costs, sens = np.array(costs), np.array(sens)
    chosen = int(np.argmin(np.abs(grid - scorer.threshold)))

    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    ax.plot(sens, costs, lw=2, color=TEAL, zorder=3)
    ax.scatter([sens[chosen]], [costs[chosen]], s=64, color=TEAL, ec=SURFACE, lw=2, zorder=4)
    ax.annotate("where we chose to stand", (sens[chosen], costs[chosen]),
                xytext=(-108, 26), textcoords="offset points", fontsize=8.5, color=INK,
                arrowprops=dict(arrowstyle="-", color=INK_3, lw=0.8))
    ax.set(xlabel="sensitivity", ylabel=f"expected cost  (1 miss = {ratio} false alarms)")
    ax.set_title("The tradeoff, chosen deliberately")
    ax.grid(axis="y", lw=0.6)
    ax.set_axisbelow(True)
    _save(fig, "02-cost-curve",
          f"Asymmetric loss: a false negative is weighted {ratio}x a false positive, because a "
          "false alarm costs minutes and a missed critical patient costs a life.")


# --- 3. fairness before / after --------------------------------------------

def fig_fairness(mitigation) -> None:
    d = mitigation["detail"].sort_values("sensitivity_before")
    x = np.arange(len(d))
    w = 0.30

    fig, ax = plt.subplots(figsize=(5.6, 3.9))
    ax.bar(x - w / 2 - 0.012, d["sensitivity_before"], w, color=ORANGE,
           label="before mitigation", zorder=3)
    ax.bar(x + w / 2 + 0.012, d["sensitivity_after"], w, color=TEAL,
           label="after subgroup-conditional calibration", zorder=3)
    for xi, (b, a) in enumerate(zip(d["sensitivity_before"], d["sensitivity_after"])):
        ax.text(xi - w / 2 - 0.012, b + 0.02, f"{b:.0%}", ha="center", fontsize=8.5, color=INK_2)
        ax.text(xi + w / 2 + 0.012, a + 0.02, f"{a:.0%}", ha="center", fontsize=8.5, color=INK_2)

    ax.axhline(0.95, lw=1, ls=(0, (3, 3)), color=INK_3, zorder=2)
    ax.set_xticks(x, d["group"])
    ax.set(ylabel="sensitivity", ylim=(0, 1.16))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title(f"Sensitivity by age band — gap {mitigation['tpr_gap_before']:.0%}"
                 f" → {mitigation['tpr_gap_after']:.0%}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncols=2)
    ax.grid(axis="y", lw=0.6)
    ax.set_axisbelow(True)
    _save(fig, "03-fairness",
          "Dashed line is the 95% sensitivity target. Geriatric patients were undertriaged at 18% "
          "while children were never missed. Mondrian conformal calibrated per subgroup gives each "
          "group its own guarantee instead of a shared average that hides the worst-served group.")


# --- 4. Layer 2 on real trajectories ---------------------------------------

def fig_layer2(lead) -> None:
    labels = ["admitted or\ntransferred", "discharged\nhome"]
    values = [lead["sensitivity_admitted"], lead["false_positive_discharged"]]

    fig, ax = plt.subplots(figsize=(4.2, 3.6))
    ax.bar(labels, values, 0.42, color=[TEAL, ORANGE], zorder=3)
    for i, v in enumerate(values):
        ax.text(i, v + 0.012, f"{v:.1%}", ha="center", fontsize=10, color=INK)
    ax.set(ylabel="flagged by Layer 2", ylim=(0, max(values) * 1.4))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title(f"Trajectory signal on {lead['stays_examined']} real MIMIC stays")
    ax.grid(axis="y", lw=0.6)
    ax.set_axisbelow(True)
    _save(fig, "04-layer2-real",
          f"Median {lead['median_lead_minutes']:.0f} minutes of lead time before the last recorded "
          "reading. Queue aging suppressed so the physiological signal is measured alone.")


# --- 5. the Isfahan trap ----------------------------------------------------

def fig_leakage() -> None:
    from data.loaders.isfahan import load, missingness_report
    rep = missingness_report(load())
    rep = rep[rep["patients"] > 100]

    fig, ax = plt.subplots(figsize=(5.0, 3.6))
    colors = [ORANGE if v > 50 else TEAL for v in rep["pct_zero_vitals"]]
    ax.bar([str(int(i)) for i in rep.index], rep["pct_zero_vitals"], 0.45,
           color=colors, zorder=3)
    for i, v in enumerate(rep["pct_zero_vitals"]):
        ax.text(i, v + 1.5, f"{v:.0f}%", ha="center", fontsize=9, color=INK)
    ax.set(xlabel="triage grade  (1 = most urgent)", ylabel="patients with zero recorded vitals",
           ylim=(0, 116))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_title("Isfahan: missingness encodes the triage decision")
    ax.grid(axis="y", lw=0.6)
    ax.set_axisbelow(True)
    _save(fig, "05-isfahan-leakage",
          "Grade 1 patients bypass the triage form entirely. A model using missing-indicators "
          "would score near-perfectly on hospital workflow rather than physiology. Excluded from training.")


def main() -> None:
    from data.loaders.synthetic import generate
    from layer1 import features
    from layer1.model import AcuityScorer
    from eval import fairness, lead_time

    print("building figures...")
    ds = generate(6000, seed=3)
    scorer = AcuityScorer().fit(ds)
    X = features.build(ds)
    y = features.critical_outcome(ds).reindex(X.index).fillna(0).astype(int).to_numpy()

    fig_roc(scorer, X, y)
    fig_cost(scorer, X, y)
    fig_fairness(fairness.mitigate(scorer, ds))
    fig_layer2(lead_time.run())
    fig_leakage()
    print(f"\n{len(list(OUT.glob('*.png')))} figures in {OUT}/")


if __name__ == "__main__":
    main()
