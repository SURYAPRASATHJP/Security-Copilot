# Evaluation report

Every number here comes from `make evals`. The golden set is generated from the advisory
corpus itself, so each answer is known without anyone labelling it. Each section is written
by the eval that produced it and assembled here, so a section is replaced when its eval is
re-run rather than appended to.

## Retrieval

10 auto-generated retrieval questions, four retrievers against both
chunking strategies.

| Retriever | Chunking | Questions | Hit rate at 5 | MRR | Seconds |
| --- | --- | --- | --- | --- | --- |
| hybrid + rerank | structured | 10 | 0.950 | 0.900 | 2 |
| bm25 | fixed | 10 | 0.400 | 0.300 | 1 |

Highest hit rate at 5: **hybrid + rerank / structured** at 0.950.
Highest MRR, and the setup that ships: **hybrid + rerank / structured** at 0.900 MRR and 0.950 hit rate at 5.

### What this table does not measure

Every generated question names its advisory or CVE id, so BM25 can match the
identifier exactly and scores far higher here than it would on the questions a
developer actually types. Read hit rate as a check that the right chunk is
reachable at all, and MRR as the honest separator: reranking is what moves the
right passage to position one. The production setup is hybrid search with
reranking over structure-aware chunks, because it is the only one that holds up
when the question does not quote an id. Removing this bias from the question set
is the first item for error analysis in Phase 3.

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

### The single agent, on a subset

The ReAct baseline was run over the first three scenarios on a day when the budget allowed
it. It is not in the table above because it covers three scenarios rather than ten, and
putting the two on one row would invite a comparison the numbers do not support.

| Agent | Scenarios | Success rate | Average steps | Tokens | Estimated cost | Seconds | Safety violations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| single agent | 3 | 0.67 | 4.7 | 44,401 | $0.0067 | 293 | 0 |
| team, same three | 3 | 1.00 | 4.0 | 0 | $0.0000 | 16 | 0 |

On the three they share, the team is right where the ReAct agent is not, eighteen times
faster, and spends no tokens. The one the ReAct agent failed, `unused-ranks-low`, it failed
by running out of its twelve step budget rather than by reaching a wrong answer, which is
the characteristic failure of asking a model to decide every step.

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

## What is not measured yet

Three measures have no committed score and are therefore not gated: answer accuracy,
refusal accuracy and citation accuracy. They need a complete 50 question run against prompt
version 3, and the free tier's rolling daily token budget has been refusing it: each answer
spends one second talking to the model and then waits one to three minutes for capacity.

A complete run on prompt version 2 gave 1.000, 1.000 and 0.000 wrong citations. Those
numbers are not carried forward here, because version 3 changed how a refusal is written and
reporting an old measurement as a current one is exactly the habit this report exists to
avoid. The thresholds go back into `docs/eval_thresholds.json` when a version 3 run lands.

Also outstanding: RAGAS as a second opinion on faithfulness, the three-model comparison, and
the red team block rate. All three are written and tested, and all three are waiting on the
same budget.
