# Evaluation report

Every number here comes from `make evals`. The golden set is generated from the advisory
corpus itself, so each answer is known without anyone labelling it. Each section is written
by the eval that produced it and assembled here, so a section is replaced when its eval is
re-run rather than appended to.

## Retrieval

200 auto-generated retrieval questions, four retrievers against both
chunking strategies.

| Retriever | Chunking | Questions | Hit rate at 5 | MRR | Seconds |
| --- | --- | --- | --- | --- | --- |
| bm25 | structured | 200 | 1.000 | 0.940 | 1 |
| hybrid | structured | 200 | 1.000 | 0.887 | 4 |
| hybrid + rerank | structured | 200 | 0.995 | 0.976 | 47 |
| hybrid + rerank | fixed | 200 | 0.520 | 0.445 | 63 |
| bm25 | fixed | 200 | 0.515 | 0.473 | 1 |
| hybrid | fixed | 200 | 0.515 | 0.345 | 4 |
| vector | structured | 200 | 0.435 | 0.317 | 3 |
| vector | fixed | 200 | 0.260 | 0.158 | 13 |

Highest hit rate at 5: **bm25 / structured** at 1.000.
Highest MRR, and the setup that ships: **hybrid + rerank / structured** at 0.976 MRR and 0.995 hit rate at 5.

### What this table does not measure

Every generated question names its advisory or CVE id, so BM25 can match the
identifier exactly and scores far higher here than it would on the questions a
developer actually types. Read hit rate as a check that the right chunk is
reachable at all, and MRR as the honest separator: reranking is what moves the
right passage to position one. The production setup is hybrid search with
reranking over structure-aware chunks, because it is the only one that holds up
when the question does not quote an id. Removing this bias from the question set
is the first item for error analysis in Phase 3.

## Answers

50 questions from the answer suite, 30 with a known
answer and 20 about packages and CVE numbers that do not exist.

| Measure | Value | Of |
| --- | --- | --- |
| Answer accuracy | 1.000 | 30 of 30 answerable |
| Refusal accuracy | 1.000 | 20 of 20 unanswerable |
| Wrong citation rate | 0.000 | 0 of 50 answers |
| Over-refusal rate | 0.000 | 0 of 30 answerable |

Correctness is checked without a model in the loop. A fixed-version answer has to
contain the version the advisory names, an is-affected answer has to agree with the
version comparison, and a what-is answer has to cite the right advisory. Whether the
prose itself is faithful is graded separately by the judge in Phase 3.

| Question kind | Correct | Asked |
| --- | --- | --- |
| fixed_version | 10 | 10 |
| is_affected | 10 | 10 |
| unanswerable | 20 | 20 |
| what_is | 10 | 10 |

## The judge

A rubric prompt scores every answer for faithfulness and correctness. The number
that matters is not the score, it is how often the judge agrees with the
deterministic check, because that is what says whether the judge can be trusted on
the questions where no deterministic check exists.

| Measure | Value |
| --- | --- |
| Answers judged | 20 |
| Mean faithfulness | 1.000 |
| Mean correctness | 0.975 |
| Agreement with the deterministic check | 100.0% |

## Models compared

The same answer questions put to 2 models on Groq, through the same prompt
and the same retrieved passages, so the only thing that changes is the model.

| Model | Questions | Accuracy | Correct refusals | Mean latency | Cost per question |
| --- | --- | --- | --- | --- | --- |
| openai/gpt-oss-120b | 12 | 1.000 | n/a | 1.07 s | $0.00042 |
| openai/gpt-oss-20b | 12 | 1.000 | n/a | 0.77 s | $0.00048 |

**openai/gpt-oss-20b** comes out ahead on these questions, at 1.000 accuracy and $0.00048 a question. openai/gpt-oss-120b is the one in use.

## Agents

The same scenarios run twice: once through a single ReAct agent holding only the
read-only tools, once through the team graph. Safety violations count any run that
wrote something without an approval, and must be zero.

| Agent | Scenarios | Success rate | Average steps | Tokens | Estimated cost | Seconds | Safety violations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| single agent | 10 | 0.40 | 6.1 | 227464 | $0.0341 | 1238 | 0 |
| team | 10 | 1.00 | 4.0 | 0 | $0.0000 | 169 | 0 |

The team spends no model tokens here, and that needs a caveat. It makes one model
call, which grades whether the retrieved passages answer the question, and on a
repeated scenario that call is served from the disk cache. The structural point
still holds: its ranking is a sort in Python and its version arithmetic is the
`packaging` library, so there is nothing else for a model to decide. The ReAct agent
asks the model to choose every step, which is what the token column shows.

Where a run did not meet its scenario:

- `unused-ranks-low` (single agent): stopped at the 12 step limit
- `usage-beats-score` (single agent): stopped at the 12 step limit
- `unpinned-flagged` (single agent): stopped at the 12 step limit
- `triage-never-writes` (single agent): stopped at the 12 step limit
- `function-not-called` (single agent): stopped at the 12 step limit
- `duplicate-cve-collapsed` (single agent): stopped at the 12 step limit

## Error analysis

Every retrieval miss, bucketed by what the question was asking for. The two setups
are the same retriever over the two chunk shapes, so the difference is the fix.

| Setup | Questions | Misses | Hit rate |
| --- | --- | --- | --- |
| hybrid + rerank over fixed chunks | 200 | 96 | 0.520 |
| hybrid + rerank over structured chunks | 200 | 1 | 0.995 |

### The fixed chunks, by bucket

| Bucket | Misses | Share |
| --- | --- | --- |
| the question asks what an advisory is about | 68 | 70.8% |
| the question is about one version of a package | 28 | 29.2% |

The biggest bucket is **the question asks what an advisory is about**, 68 of 96 misses. The fix was the chunk shape rather than the
retriever: a fixed-size window splits an advisory so that the half naming the
package is not the half naming the version, and a question about a version
then matches neither. Giving every chunk a context header and a summary card
took this setup from 0.520 to 0.995.

### What still misses with structured chunks

- the question is about one version of a package: 1

A few of the questions that missed:

- `fixed_version:GHSA-9ggr-2464-2j32:authlib`: Which version of authlib fixes GHSA-9ggr-2464-2j32?
- `fixed_version:PYSEC-2026-1994:urllib3`: Which version of urllib3 fixes PYSEC-2026-1994?
- `fixed_version:GHSA-hgf8-39gv-g3f2:werkzeug`: Which version of werkzeug fixes GHSA-hgf8-39gv-g3f2?
- `fixed_version:PYSEC-2026-1518:langchain-core`: Which version of langchain-core fixes PYSEC-2026-1518?
- `fixed_version:PYSEC-2026-3787:gitpython`: Which version of gitpython fixes PYSEC-2026-3787?

## Cost and latency

Every real call to the model is logged to `data/llm_calls.jsonl` with its tokens,
latency and cost. Latency is the attempt that succeeded, so time spent waiting out
a rate limit is not counted as the model being slow. Cached replies make no call
and appear nowhere here, which is why the totals are lower than the questions
asked.

| Measure | Value |
| --- | --- |
| Real API calls logged | 243 |
| Total spend | $0.0792 |
| p50 latency | 1.03 s |
| p95 latency | 2.24 s |
| Cost per answered question | $0.00034 |
| Cost per repository scan | $0.00021 |

| Prompt | Calls | Mean tokens | Mean cost | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| answer_question | 225 | 1398 | $0.00034 | 1.04 s | 2.01 s |
| budget_probe | 1 | 111 | $0.00003 | 0.45 s | 0.45 s |
| check_groq_connection | 3 | 141 | $0.00005 | 0.59 s | 1.15 s |
| grade_passages | 6 | 782 | $0.00021 | 306.63 s | 480.16 s |
| probe | 4 | 110 | $0.00003 | 0.41 s | 0.59 s |
| probe2 | 1 | 110 | $0.00003 | 0.46 s | 0.46 s |
| unnamed | 3 | 112 | $0.00003 | 0.40 s | 0.51 s |

## Load

20 concurrent users against `/check-dependencies` for two minutes, on the laptop that built
the index. This measures how much the service can take, not what a public demo allows: the
rate limits are on only when `COPILOT_DEMO_MODE` is set, and they were off for this run.

| Measure | Value |
| --- | --- |
| Requests completed | 5,774 |
| Requests per second | 48.1 |
| Errors | 0 |
| p50 latency | 0.408 s |
| p95 latency | 0.470 s |
| p99 latency | 0.653 s |

The endpoint calls OSV over the network and then joins the local corpus, so this is mostly a
measure of how that join holds up under concurrency. Answering is a different shape of
problem: it is bounded by the model's 8,000 tokens a minute rather than by this machine,
which is why the public demo limits `/ask` to six requests a minute per visitor.

## What is not measured yet

Two things are left, both written and tested, both waiting on the free tier's rolling daily
token budget: RAGAS as a second opinion on faithfulness, and a re-run of the model
comparison to regenerate its section.

The model comparison ships with two models rather than three. Groq no longer offers a
general purpose Llama chat model on this account, and `openai/gpt-oss-safeguard-20b` is
capped at 2,000 tokens a minute against a 2,647 token prompt, so it cannot serve a single
request at any pace. The reasoning is in `docs/decisions.md`.
