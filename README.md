# Security Copilot

Tells you whether your Python dependencies have known vulnerabilities, explains each one
with a cited advisory, and opens a pull request that fixes it.

Version ranges are decided by code, never by the model. The model explains what an
advisory means; `packaging` decides whether your pinned version is inside the affected
range. Getting that boundary wrong is the usual way a tool like this starts inventing
answers.

## Status

Phase 0 of 3 is complete: settings, the Groq client with retries, caching and per-call
cost logging, lint, tests and CI.

## Run it

```sh
cp .env.example .env     # then paste your key from console.groq.com after GROQ_API_KEY=
make setup               # install every dependency group into .venv
make test                # run the suite
make lint                # ruff check and format check
uv run python scripts/check_groq_connection.py
```

`make help` lists every target. Targets for later phases say which phase they arrive in.

## How it is put together

| Piece | Where | What it does |
| --- | --- | --- |
| Settings | `src/copilot/settings.py` | One place for the model name, prices, paths and keys, read from `.env` |
| LLM client | `src/copilot/llm_client.py` | Groq through the `openai` SDK, with backoff on 429 and 5xx, a disk cache, JSON Schema mode and a cost log |
| Decisions | `docs/decisions.md` | Every design choice, the options compared, and the evidence |

Keys live only in `.env`, which is ignored by git from the first commit. Nothing is
printed or logged.

## Data sources

OSV, the NVD CVE API, FIRST EPSS and the CISA Known Exploited Vulnerabilities catalogue.
All public, no key required.
