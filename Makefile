.PHONY: help setup test status demo extract-yale clean

help:
	@echo "ATRIA — Accenture Innovation Challenge 2026, Track 2"
	@echo ""
	@echo "  make setup         create .venv and install dependencies"
	@echo "  make test          run the full test suite"
	@echo "  make demo          start the live board on :8000"
	@echo "  make status        show which data sources are ready"
	@echo "  make extract-yale  extract the Yale slim CSV (needs R)"

setup:
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -r requirements.txt

test:
	.venv/bin/python -m pytest tests/ -q

demo:
	.venv/bin/uvicorn service.app:app --host 127.0.0.1 --port 8000

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
