.PHONY: help setup test test-all status demo streamlit scenarios eval fairness figures report extract-yale clean

help:
	@echo "ATRIA — Accenture Innovation Challenge 2026, Track 2"
	@echo ""
	@echo "  make setup         create .venv and install dependencies"
	@echo "  make test          run the test suite (skips slow measurement runs)"
	@echo "  make test-all      everything, including figure and report generation"
	@echo "  make demo          start the live board on :8000 (FastAPI)"
	@echo "  make streamlit     start the Streamlit board on :8501"
	@echo "  make web           start the Next.js client on :3000 (needs make demo too)"
	@echo "  make status        show which data sources are ready"
	@echo "  make scenarios     run the six demo scenarios"
	@echo "  make eval          latency, cross-site and Layer 2 lead time"
	@echo "  make fairness      subgroup audit and mitigation"
	@echo "  make figures       export the deck figures"
	@echo "  make report        regenerate docs/results.md from live measurements"
	@echo "  make extract-yale  extract the Yale slim CSV (needs R)"

setup:
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -r requirements-dev.txt

test:
	.venv/bin/python -m pytest tests/ -m "not slow"

test-all:
	.venv/bin/python -m pytest tests/

demo:
	.venv/bin/uvicorn service.app:app --host 127.0.0.1 --port 8000

streamlit:
	.venv/bin/streamlit run streamlit_app.py

web:
	@test -d atria-web/node_modules || (cd atria-web && npm install)
	cd atria-web && npm run dev

scenarios:
	.venv/bin/python -m scenarios.run

eval:
	@.venv/bin/python -m eval.latency
	@echo ""
	@.venv/bin/python -m eval.lead_time
	@echo ""
	@.venv/bin/python -m eval.cross_site

fairness:
	.venv/bin/python -m eval.fairness

figures:
	.venv/bin/python -m eval.figures

report: figures
	.venv/bin/python -m eval.report

status:
	@.venv/bin/python -c "import data.loaders as L; \
	  [print(('  ready    ' if ok else '  MISSING  ')+n) for n,ok in L.available().items()]"

extract-yale:
	@command -v Rscript >/dev/null 2>&1 || { \
	  echo "R not installed. Run: sudo apt install r-base"; exit 1; }
	Rscript data/yale/extract_yale.R

clean:
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
