# DevOps Agent — Makefile
# Pinned to python3.12 (matches the physical server's Python 3.12.3).
# Override via PYTHON=python3.13 if you need to experiment.

PYTHON     ?= python3.12
AGENT_PORT ?= 8100
VENV_BIN    = .venv/bin

.PHONY: help install dev run test lint format typecheck clean reset

help:
	@echo "DevOps Agent — make targets"
	@echo "  install    Create .venv (python3.12) and install deps + dev extras"
	@echo "  dev        Run FastAPI with --reload on :$(AGENT_PORT)"
	@echo "  run        Run FastAPI (no reload) on :$(AGENT_PORT)"
	@echo "  test       Run pytest"
	@echo "  lint       ruff check + ruff format --check"
	@echo "  format     ruff format + ruff check --fix"
	@echo "  typecheck  mypy on first-party packages"
	@echo "  clean      Remove .venv and all caches"
	@echo "  reset      clean + install (fresh venv)"

install:
	@command -v $(PYTHON) >/dev/null 2>&1 || { \
		echo "ERROR: $(PYTHON) not on PATH."; \
		echo "       Install via: brew install python@3.12"; \
		exit 1; \
	}
	$(PYTHON) -m venv .venv
	$(VENV_BIN)/pip install --upgrade pip
	$(VENV_BIN)/pip install -e ".[dev]"
	@echo ""
	@echo "✅ venv ready. Activate with: source .venv/bin/activate"

dev:
	$(VENV_BIN)/uvicorn api.main:app --reload --host 0.0.0.0 --port $(AGENT_PORT)

run:
	$(VENV_BIN)/uvicorn api.main:app --host 0.0.0.0 --port $(AGENT_PORT)

test:
	@$(VENV_BIN)/pytest tests/; ec=$$?; \
	if [ $$ec -eq 5 ]; then echo "(no tests collected — acceptable pre-Phase 2)"; exit 0; else exit $$ec; fi

lint:
	$(VENV_BIN)/ruff check .
	$(VENV_BIN)/ruff format --check .

format:
	$(VENV_BIN)/ruff format .
	$(VENV_BIN)/ruff check --fix .

typecheck:
	$(VENV_BIN)/mypy agents/ api/ tools/ utils/ telegram_bot/ config/

clean:
	rm -rf .venv __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf *.egg-info build dist .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

reset: clean install
