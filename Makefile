.DEFAULT_GOAL := help
.PHONY: help setup data index api app evals test lint

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-8s %s\n", $$1, $$2}'

setup:  ## Install every dependency group into .venv
	uv sync

data:  ## Download and merge the advisory corpus
	@echo "Available after Phase 1."

index:  ## Build the vector and keyword search indexes
	@echo "Available after Phase 1."

api:  ## Serve the FastAPI backend
	@echo "Available after Phase 1."

app:  ## Serve the Streamlit interface
	@echo "Available after Phase 1."

evals:  ## Run every eval and rewrite docs/eval_report.md
	@echo "Available after Phase 3."

test:  ## Run the test suite
	uv run pytest -q

lint:  ## Check formatting and lint rules
	uv run ruff check .
	uv run ruff format --check .
