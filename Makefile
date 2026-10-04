.DEFAULT_GOAL := help
.PHONY: help setup data index api app evals test lint

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-8s %s\n", $$1, $$2}'

setup:  ## Install every dependency group into .venv
	uv sync

data:  ## Download and merge the advisory corpus
	uv run python -m copilot.data_collection.download_osv_advisories
	uv run python -m copilot.data_collection.scope_to_top_packages
	uv run python -m copilot.data_collection.fetch_nvd_details
	uv run python -m copilot.data_collection.fetch_exploit_signals
	uv run python -m copilot.data_collection.merge_into_one_record

index:  ## Build the vector and keyword search indexes
	uv run python -m copilot.rag.split_into_chunks
	uv run python -m copilot.rag.build_search_index
	uv run python -m copilot.evals.build_golden_questions

api:  ## Serve the FastAPI backend
	uv run uvicorn api.main:app --reload --port 8000

app:  ## Serve the Streamlit interface
	uv run streamlit run app/streamlit_app.py

evals:  ## Run every eval and rewrite docs/eval_report.md
	uv run python -m copilot.evals.run_all_evals

test:  ## Run the test suite
	uv run pytest -q

lint:  ## Check formatting and lint rules
	uv run ruff check .
	uv run ruff format --check .
