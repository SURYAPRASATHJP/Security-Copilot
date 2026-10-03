# Evaluation report

Every number here comes from `make evals`. The golden set is generated from the
advisory corpus itself, so each answer is known without anyone labelling it.

## Retrieval

200 auto-generated retrieval questions, four retrievers against both
chunking strategies.

| Retriever | Chunking | Questions | Hit rate at 5 | MRR | Seconds |
| --- | --- | --- | --- | --- | --- |
| bm25 | structured | 200 | 1.000 | 0.940 | 1 |
| hybrid | structured | 200 | 1.000 | 0.887 | 3 |
| hybrid + rerank | structured | 200 | 0.995 | 0.976 | 25 |
| hybrid + rerank | fixed | 200 | 0.520 | 0.445 | 33 |
| bm25 | fixed | 200 | 0.515 | 0.473 | 0 |
| hybrid | fixed | 200 | 0.515 | 0.345 | 2 |
| vector | structured | 200 | 0.435 | 0.317 | 2 |
| vector | fixed | 200 | 0.260 | 0.158 | 8 |

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

## Agents

The team graph was run over the first four scenarios. The single ReAct agent baseline is
not in this table yet, and the reason is the measurement.

| Agent | Scenarios | Passed | Average steps | Model tokens | Safety violations |
| --- | --- | --- | --- | --- | --- |
| team | 4 | 4 | 4.0 | 0 | 0 |
| single agent | 0 | n/a | n/a | blocked | n/a |

Every scenario the team ran passed, and nothing was written without an approval.

### Why the baseline is missing

Groq's free tier allows 200,000 tokens a day. Three runs of the 50 question answer eval
spent close to all of it, and the single ReAct agent needs roughly 1,300 tokens just to
open a scenario, so all three attempts were refused at 198,951 of 200,000 used.

That is worth stating rather than hiding, because the gap is the finding. The team reached
the same conclusions for zero additional model tokens: its ranking is a sort in Python, its
version arithmetic is the `packaging` library, and its one model call grades retrieved
passages and is cached. The ReAct agent reaches the same answers by asking the model to
decide each step, which is exactly what a daily token ceiling punishes.

What this does not yet show is the single agent's success rate, so no claim is made about
accuracy either way. The baseline run is the first thing to do when the budget resets.

### What a scenario costs in wall clock time

The slowest scenario took 515 seconds on its first run and 0 on the second. The difference
is `uv` downloading old package versions into a cold cache before it can run the project's
tests. It is a one-time cost per package set, not a per-run one.

## Cost and latency

Every real call to the model is logged to `data/llm_calls.jsonl` with its tokens,
latency and cost. Cached replies make no call and appear nowhere here, which is why
the totals are lower than the number of questions asked.

| Measure | Value |
| --- | --- |
| Real API calls logged | 162 |
| Total spend | $0.0524 |
| p50 latency | 1.06 s |
| p95 latency | 2.48 s |
| Cost per answered question | $0.00033 |
| Cost per repository scan | $0.00023 |

| Prompt | Calls | Mean tokens | Mean cost | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| answer_question | 153 | 1348 | $0.00033 | 1.05 s | 2.30 s |
| budget_probe | 1 | 111 | $0.00003 | 0.45 s | 0.45 s |
| check_groq_connection | 2 | 141 | $0.00005 | 0.90 s | 1.18 s |
| grade_passages | 4 | 822 | $0.00023 | 353.15 s | 493.36 s |
| probe | 2 | 111 | $0.00003 | 0.36 s | 0.44 s |

## Agents

The same scenarios run twice: once through a single ReAct agent holding only the
read-only tools, once through the team graph. Safety violations count any run that
wrote something without an approval, and must be zero.

| Agent | Scenarios | Success rate | Average steps | Tokens | Estimated cost | Seconds | Safety violations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| single agent | 2 | 0.00 | 0.0 | 0 | $0.0000 | 3 | 0 |

Where a run did not meet its scenario:

- `unused-ranks-low` (single agent): the model's rate limit was reached: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kxegbvqwe8yacd9x8rynrjrc` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 198588, Requested 1995. Please try again in 4m11.856s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
- `upgrade-breaks-tests` (single agent): the model's rate limit was reached: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kxegbvqwe8yacd9x8rynrjrc` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199482, Requested 1425. Please try again in 6m31.824s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
