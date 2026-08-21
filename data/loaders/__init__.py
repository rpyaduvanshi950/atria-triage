"""Loader registry. Every source returns the same contract; nothing above cares which."""
from __future__ import annotations

from contracts.schema import Dataset

from . import isfahan, mimic_demo, synthetic, yale

LOADERS = {
    "yale": yale.load,
    "mimic_demo": mimic_demo.load,
    "isfahan": isfahan.load,
    "synthetic": synthetic.generate,
}


def load(name: str, **kw) -> Dataset:
    """Load a source by name. Extra kwargs go to the loader (e.g. synthetic n=, seed=)."""
    if name not in LOADERS:
        raise KeyError(f"unknown source {name!r}; have {sorted(LOADERS)}")
    return LOADERS[name](**kw)


def available() -> dict[str, bool]:
    """Which sources are ready to load right now."""
    out = {}
    for name, fn in LOADERS.items():
        try:
            fn()
            out[name] = True
        except FileNotFoundError:
            out[name] = False
    return out
