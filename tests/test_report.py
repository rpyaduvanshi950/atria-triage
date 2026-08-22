"""
The deck's numbers must come from the code, not from a person's memory.

Marked slow: these re-run every measurement in eval/, which takes minutes. They
run in `make test-all`, and before any commit that touches the figures.
"""
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def test_figures_export(tmp_path, monkeypatch):
    from eval import figures
    monkeypatch.setattr(figures, "OUT", tmp_path / "figs")
    figures.main()
    written = sorted(p.name for p in (tmp_path / "figs").glob("*.png"))
    assert len(written) == 5
    assert written[0].startswith("01-")


def test_report_regenerates_and_states_its_limitations(tmp_path, monkeypatch):
    from eval import report
    monkeypatch.setattr(report, "OUT", tmp_path / "results.md")
    report.main()
    text = (tmp_path / "results.md").read_text()

    for section in ("Layer 1", "Mondrian conformal coverage", "Fairness",
                    "Latency", "The Isfahan trap", "Stated limitations"):
        assert section in text, f"missing section: {section}"

    # the limitations must not quietly disappear when results improve
    assert "not yet extracted" in text or "Yale" in text
    assert "159 real trajectories" in text
