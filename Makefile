.PHONY: help setup test test-all status demo streamlit scenarios eval fairness figures report extract-yale freeze shadow explainer readme-pdf build-log-pdf clean

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
	@echo "  make freeze        train once and pin the model artifact + manifest"
	@echo "  make shadow        start the board in shadow mode (nothing acts)"
	@echo "  make explainer     re-render the plain-words PDF from its HTML source"
	@echo "  make readme-pdf    render README.md to docs/pdf/ATRIA-README.pdf"
	@echo "  make build-log-pdf render the full engineering record to PDF"

setup:
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -r requirements-dev.txt

test:
	.venv/bin/python -m pytest tests/ -m "not slow"

test-all:
	.venv/bin/python -m pytest tests/

demo:
	ATRIA_DB=data/atria_audit.db \
	  .venv/bin/uvicorn service.app:app --host 127.0.0.1 --port 8000

# Phase 1 of the deployment roadmap: every layer runs, nothing moves the board.
shadow:
	ATRIA_SHADOW=1 ATRIA_DB=data/atria_shadow.db \
	  .venv/bin/uvicorn service.app:app --host 127.0.0.1 --port 8000

freeze:
	.venv/bin/python -m ml.freeze

# Edit docs/pdf/atria-explained.html, then re-render. WeasyPrint comes from the
# system, not the venv: `sudo apt install weasyprint`.
# The README is the submission document and a judge may read it printed.
readme-pdf:
	.venv/bin/python docs/pdf/build_readme_pdf.py readme

# The full engineering record: every decision, and every bug with how it was
# found. Local only; docs/ is not tracked.
build-log-pdf:
	.venv/bin/python docs/pdf/build_readme_pdf.py build-log

explainer:
	@command -v weasyprint >/dev/null 2>&1 || { \
	  echo "weasyprint not installed. Run: sudo apt install weasyprint"; exit 1; }
	weasyprint docs/pdf/atria-explained.html docs/pdf/ATRIA-explained.pdf
	@echo "wrote docs/pdf/ATRIA-explained.pdf"

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
