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
| 2026-09-23 | The corpus is scoped to advisories for the 300 most-downloaded PyPI packages | all 31,220 PyPI advisories, the top 1,000 packages, the top 300 | NVD allows 5 requests per 30 seconds without a key, so a focused corpus is the difference between 70 minutes of enrichment and three days of it; the top 300 still cover the packages a real requirements.txt is made of | 1,502 advisories over 102 packages and 705 CVEs, from `scope_to_top_packages.py` |
| 2026-09-24 | Whether a pinned version is affected is decided by code, never by the model | ask the model to compare versions, OSV querybatch plus the `packaging` library, hand-rolled range comparison | Version comparison is exactly where a language model invents a plausible wrong answer, and the mistake is invisible to the person reading it; the model's job is to explain an advisory, not to do arithmetic | 8 of 8 demo packages resolved with no model call, in `check_my_dependencies.py` |
| 2026-09-24 | Advisories that describe the same CVE for the same package collapse into one finding | list every advisory id, collapse by shared CVE and keep the GHSA record, collapse by package | GHSA and PYSEC both publish the same CVE, so the demo app reported the same eight problems twice and the real count was unreadable | 93 findings became 50 on the same requirements file |
| 2026-09-24 | Dependency checking is its own package, not part of `rag/` | put it under `rag/`, put it under `data_collection/`, give it `dependencies/` | Nothing in it retrieves or embeds anything, and a reader looking for the version logic should not have to open a retrieval folder to find it | `src/copilot/dependencies/` |
| 2026-09-26 | Retrieval runs as hybrid search plus a cross-encoder rerank over structure-aware chunks | 8 setups: BM25, vector, hybrid and hybrid plus rerank, each over fixed-size and structure-aware chunks | Chunking mattered far more than the retriever: BM25 went from 0.510 to 1.000 hit rate at 5 purely by giving every chunk a context header and a summary card. Among the structured setups, reranking is what moves the right passage to position one | hit rate at 5 and MRR over 200 generated questions, in `docs/eval_report.md` |
| 2026-09-26 | The generated question set is treated as an ID-matching benchmark, not a realistic one | accept the numbers as they are, hand-write realistic questions, generate paraphrases without the id | Every generated question quotes its advisory or CVE id, which is exactly what BM25 is best at, so its 1.000 hit rate flatters it. Saying so is worth more than a number that will not survive a real user | BM25 1.000 hit rate but 0.940 MRR against 0.995 and 0.975 for hybrid plus rerank; the gap is where reranking earns its place |
| 2026-09-26 | Answer correctness is checked by code first and left to a model judge only where prose makes that impossible | a model judge for everything, exact string checks for everything, a split | A fixed version and a yes or no have exactly one right answer, and asking a model to grade those just adds a second thing that can be wrong | `is_correct` in `answer_metrics.py` grades two of the three kinds with no model in the loop |
| 2026-09-26 | A GIT range in an OSV record is ignored; only ECOSYSTEM and SEMVER ranges decide whether a version is affected | parse every range type, ignore GIT ranges, try to resolve commits to versions | PYSEC records carry a git range whose bounds are commit hashes. Reading one as a version produced an open-ended window that marked every release affected, so the fix finder returned nothing for every package and the summary cards advertised a commit hash as the fixed version | all 8 demo packages went from no safe version to a concrete one, for example requests 2.27.1 to 2.33.0 |
| 2026-09-27 | The copilot answers general security questions from its own knowledge, but a claim about a specific advisory, package or version must come from the retrieved context | refuse anything not in the corpus, answer everything, split by what kind of claim it is | Refusing "what is a ReDoS" the same way it refuses a made-up CVE makes the tool feel broken, but letting it speak freely about versions is exactly how it would start inventing fixes. The split keeps the guarantee where it matters, which is anything a developer would act on | prompt version 2; refusal accuracy held at 1.000 on 20 invented CVEs and packages |
| 2026-09-30 | Agent runs are budgeted and batched against a 200,000 token daily ceiling | run freely and retry on failure, cap tokens per run, cap tokens and cap tool output | The free Groq tier allows 200K tokens a day and three runs of a 50 question eval very nearly spends all of it. One unbounded agent run over a repository with 50 findings would spend a large part of a day's budget in a single pass | the lookup tool returns 10 findings rather than 50, a run stops at 60,000 tokens or 12 steps, and a rate limit is reported as a partial result rather than a crash |

## Tool permissions

Seven tools are served over MCP. Five cannot change anything. The two that can are fenced
in by what they are allowed to touch, not by asking the model to behave.

| Tool | Reads | Writes | May touch | Hard limits |
| --- | --- | --- | --- | --- |
| `scan_repository_for_packages` | the repository | nothing | nothing | clones into a temporary folder, refuses any zip entry that escapes it |
| `look_up_vulnerabilities` | OSV and the local corpus | nothing | nothing | returns the worst 10 findings by default, never the whole list |
| `check_if_code_uses_the_package` | the repository's Python files | nothing | nothing | parses with `ast`, never imports or runs the code |
| `find_the_lowest_safe_version` | PyPI and the local corpus | nothing | nothing | only ever returns a version PyPI actually serves |
| `run_the_project_tests` | the repository | a throwaway environment | a temporary directory it creates and deletes | 5 minute timeout, the environment never touches the repository |
| `update_the_requirements_file` | the repository | one file | `requirements*.txt` only | refuses any other filename, refuses `main`, `master`, `trunk` and `develop`, needs approval first |
| `open_a_pull_request` | nothing | a pull request | one branch to one base | refuses a protected head branch, refuses head equal to base, opens as a draft by default, needs approval first |

The triage agent is handed only the five read-only tools, so it cannot write even if it
decides it wants to. The team's Fixer gets the write tools, and every call to one passes
through `human_approval.py` first: the graph stops, the planned change is shown as a diff,
and nothing is written until a person approves or edits it. A rejection raises rather than
falling through to a default.

The GitHub token is never stored by this project. `open_a_pull_request` reads it from the
`gh` login the user already has, so revoking access is something the user does in one place
and this repository holds no secret to leak.
