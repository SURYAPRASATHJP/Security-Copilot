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
