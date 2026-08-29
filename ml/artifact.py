"""
Freezing and loading the Layer 1 model.

Retraining at startup means no two deployments are provably the same model, and
an audit entry that records "model_version" is worthless if the version cannot
be tied to an artifact anyone can inspect. It also costs ten seconds every boot.

The manifest is the point, more than the pickle. It records what the model was
trained on, which features it accepts, where its operating point sits and what
it scored — so a decision logged six months ago can be traced to the exact model
that made it.
"""
from __future__ import annotations

import hashlib
import json
import pickle
from datetime import date
from pathlib import Path
from typing import Any

MODEL_DIR = Path("ml/models")
MODEL_FILE = MODEL_DIR / "acuity.pkl"
MANIFEST_FILE = MODEL_DIR / "manifest.json"

#: Bump when the feature contract or training procedure changes in a way that
#: makes an older artifact unsafe to load.
ARTIFACT_VERSION = "1"


def _fingerprint(paths: list[Path]) -> dict[str, str]:
    """Hash of the training inputs, so a manifest names its data unambiguously."""
    out: dict[str, str] = {}
    for p in paths:
        if not p.exists():
            continue
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out[p.name] = h.hexdigest()[:16]
    return out


def save(scorer, *, source: str, training_files: list[str] | None = None) -> dict[str, Any]:
    """Freeze a trained scorer and write the manifest beside it."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    # Stamped before pickling so the version travels with the model rather than
    # living only in a manifest that could be read against the wrong file.
    scorer.model_version = f"acuity-{date.today().isoformat()}-{ARTIFACT_VERSION}"
    MODEL_FILE.write_bytes(pickle.dumps(scorer))

    manifest = {
        "artifact_version": ARTIFACT_VERSION,
        "model_version": scorer.model_version,
        "trained_on": source,
        "training_data": _fingerprint([Path(f) for f in (training_files or [])]),
        "features": list(scorer.columns),
        "n_features": len(scorer.columns),
        "features_dropped": list(getattr(scorer, "metrics_dropped", [])),
        "unsafe_missing_clamped": list(getattr(scorer, "unsafe_missing", [])),
        "operating_point": {
            "sensitivity_target": scorer.sensitivity_target,
            "threshold": scorer.threshold,
            "band_cuts": scorer.band_cuts,
        },
        "conformal_alpha": scorer.alpha,
        "metrics": scorer.metrics,
        "sha256": hashlib.sha256(MODEL_FILE.read_bytes()).hexdigest(),
        "size_bytes": MODEL_FILE.stat().st_size,
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


def manifest() -> dict[str, Any] | None:
    if not MANIFEST_FILE.exists():
        return None
    return json.loads(MANIFEST_FILE.read_text())


def load():
    """
    Load the frozen model, or None if there is not a trustworthy one.

    Refuses an artifact whose bytes do not match the manifest, and one written
    by an incompatible artifact version. Falling back to training is safe;
    loading a model that is not the one the manifest describes is not.
    """
    m = manifest()
    if m is None or not MODEL_FILE.exists():
        return None
    if m.get("artifact_version") != ARTIFACT_VERSION:
        return None
    blob = MODEL_FILE.read_bytes()
    if hashlib.sha256(blob).hexdigest() != m.get("sha256"):
        return None
    return pickle.loads(blob)


def load_or_train(fallback, *, source: str = "synthetic fallback"):
    """
    Prefer the frozen artifact; train only if there is not a usable one.

    Callers pass a zero-argument `fallback` that returns a freshly trained
    scorer. A checked-out repo with no artifact still runs — it just pays the
    training cost and logs that it is not running the frozen model.
    """
    scorer = load()
    if scorer is not None:
        print(f"[atria] loaded frozen model {manifest()['model_version']} "
              f"(AUC {manifest()['metrics'].get('auc')})")
        return scorer
    print(f"[atria] no frozen model artifact — training from {source}. "
          f"Run `make freeze` to pin one.")
    return fallback()
