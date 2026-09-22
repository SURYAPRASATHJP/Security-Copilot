# Design decisions

Every choice worth defending, the options that were on the table, the reason one won, and
the evidence that says it was right. Newest rows go at the bottom.

| Date | Decision | Options compared | Why | Evidence |
| --- | --- | --- | --- | --- |
| 2026-09-21 | Groq `openai/gpt-oss-120b` is the only answering model | `gpt-oss-120b`, `gpt-oss-20b`, a hosted frontier model | 131k context, tool calling and JSON Schema mode on a free tier that needs no card, which keeps the whole project at zero cost | Measured against two other Groq models in task 3.6 |
| 2026-09-21 | Call Groq through the `openai` SDK with a custom `base_url` | native Groq SDK, `openai` SDK, LiteLLM | One client shape for every call, and OpenInference instruments it without a shim, so tracing arrives free in Phase 3 | `src/copilot/llm_client.py` |
| 2026-09-21 | Dependencies live in five PEP 735 groups, not one flat list | one list, extras, dependency groups | The Docker image can install the serving groups and skip dev and ML, while `uv sync` stays a single command for laptops | `default-groups` in `pyproject.toml` installs all five |
| 2026-09-21 | Every LLM reply is cached on disk, keyed by model, messages, schema and temperature | no cache, in-process dict, `diskcache` on disk | The Groq free tier allows 200K tokens a day, so re-running an eval set must cost nothing after the first pass | A repeated question makes zero API calls and writes no second log line |
| 2026-09-21 | Retry waits take the larger of exponential backoff and the `retry-after` header | fixed sleep, exponential only, max of both | Sleeping for less than Groq asks just burns another of the five attempts without getting an answer | Tests drive a 429 with a header and a 500 through to success |
| 2026-09-22 | CI installs every dependency group from the lockfile | core and dev only, all groups | Phase 1 and 2 tests import chromadb and langgraph, and a hand-picked CI install would silently go stale | `.github/workflows/tests.yml` runs `uv sync --frozen` |
| 2026-09-21 | A missing `GROQ_API_KEY` raises one named error rather than failing at the HTTP layer | let the API return 401, assert at import time, raise on first use | Data collection and retrieval work with no key at all, so the check belongs at the first LLM call and must name the file to edit | `require_groq_key` and `test_missing_key_names_the_file_to_edit` |
