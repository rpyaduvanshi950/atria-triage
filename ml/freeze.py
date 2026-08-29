"""Train once and freeze. Run: make freeze"""
from __future__ import annotations

import json

import data.loaders as loaders
from data.loaders.synthetic import generate
from layer1.model import AcuityScorer
from ml import artifact


def main() -> None:
    try:
        ds = loaders.load("yale")
        source = f"Yale ED, {len(ds.edstays):,} real encounters (Hong et al. 2018)"
        files = ["data/yale/yale_triage_slim.csv"]
    except FileNotFoundError:
        ds = generate(6000, seed=3)
        source = "synthetic, fitted to Isfahan priors (Yale not extracted)"
        files = ["data/isfahan_priors.json"]

    print(f"training on {source} …")
    scorer = AcuityScorer().fit(ds)
    m = artifact.save(scorer, source=source, training_files=files)

    print(json.dumps({k: m[k] for k in
                      ("model_version", "trained_on", "n_features", "sha256")}, indent=2))
    print(f"AUC {m['metrics'].get('auc')} · wrote {artifact.MODEL_FILE}")


if __name__ == "__main__":
    main()
