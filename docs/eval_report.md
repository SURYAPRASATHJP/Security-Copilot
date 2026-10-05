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
| hybrid + rerank | structured | 200 | 0.995 | 0.976 | 48 |
| hybrid + rerank | fixed | 200 | 0.520 | 0.445 | 63 |
| bm25 | fixed | 200 | 0.515 | 0.473 | 1 |
| hybrid | fixed | 200 | 0.515 | 0.345 | 4 |
| vector | structured | 200 | 0.435 | 0.317 | 3 |
| vector | fixed | 200 | 0.260 | 0.158 | 12 |

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

1 questions from the answer suite, 1 with a known
answer and 0 about packages and CVE numbers that do not exist.

| Measure | Value | Of |
| --- | --- | --- |
| Answer accuracy | 1.000 | 1 of 1 answerable |
| Refusal accuracy | 0.000 | 0 of 0 unanswerable |
| Wrong citation rate | 0.000 | 0 of 1 answers |
| Over-refusal rate | 0.000 | 0 of 1 answerable |

Correctness is checked without a model in the loop. A fixed-version answer has to
contain the version the advisory names, an is-affected answer has to agree with the
version comparison, and a what-is answer has to cite the right advisory. Whether the
prose itself is faithful is graded separately by the judge in Phase 3.

| Question kind | Correct | Asked |
| --- | --- | --- |
| fixed_version | 1 | 1 |

## Agents

The same scenarios run twice: once through a single ReAct agent holding only the
read-only tools, once through the team graph. Safety violations count any run that
wrote something without an approval, and must be zero.

| Agent | Scenarios | Success rate | Average steps | Tokens | Estimated cost | Seconds | Safety violations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| team | 10 | 1.00 | 4.0 | 0 | $0.0000 | 479 | 0 |

The team spends no model tokens here, and that needs a caveat. It makes one model
call, which grades whether the retrieved passages answer the question, and on a
repeated scenario that call is served from the disk cache. The structural point
still holds: its ranking is a sort in Python and its version arithmetic is the
`packaging` library, so there is nothing else for a model to decide. The ReAct agent
asks the model to choose every step, which is what the token column shows.

## Cost and latency

Every real call to the model is logged to `data/llm_calls.jsonl` with its tokens,
latency and cost. Latency is the attempt that succeeded, so time spent waiting out
a rate limit is not counted as the model being slow. Cached replies make no call
and appear nowhere here, which is why the totals are lower than the questions
asked.

| Measure | Value |
| --- | --- |
| Real API calls logged | 175 |
| Total spend | $0.0551 |
| p50 latency | 1.04 s |
| p95 latency | 2.48 s |
| Cost per answered question | $0.00033 |
| Cost per repository scan | $0.00023 |

| Prompt | Calls | Mean tokens | Mean cost | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| answer_question | 164 | 1327 | $0.00033 | 1.04 s | 2.24 s |
| budget_probe | 1 | 111 | $0.00003 | 0.45 s | 0.45 s |
| check_groq_connection | 2 | 141 | $0.00005 | 0.90 s | 1.18 s |
| grade_passages | 4 | 822 | $0.00023 | 353.15 s | 493.36 s |
| probe | 4 | 110 | $0.00003 | 0.41 s | 0.59 s |

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
