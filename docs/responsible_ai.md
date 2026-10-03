# Responsible use

## The risk that matters

A security tool that misses something is worse than no tool, because it replaces a vague
unease with a false sense of safety. Someone who runs this and sees a short list will stop
looking. That is the failure this project is designed around, and it is why the interface
says so on every page rather than burying it here.

Three things follow from it.

**The corpus is scoped, and the scope is stated.** Advisories are limited to the 300
most-downloaded PyPI packages. A vulnerability in a package outside that list will not be
found, and the tool does not pretend otherwise. The scope is in the README, not a footnote.

**A clean result is a statement about public databases on a given day.** OSV, NVD, EPSS and
the CISA catalogue are not complete and are not instant. An advisory published this morning
is not in yesterday's index, which is why `refresh_index_daily.py` exists and why the
interface says what it is reporting rather than claiming your project is safe.

**Nothing silently decides a version is fine.** Whether a pin falls in an affected range is
decided by the `packaging` library, never by the model. If a version cannot be parsed, the
answer is "not affected by this check", not a guess, and the warning is shown.

## Where the model is allowed to speak

| The model does | The model never does |
| --- | --- |
| Explain what an advisory means | Decide whether a version is affected |
| Explain a class of weakness in general terms | Invent an advisory id, package or version |
| Extract a named function from advisory text | Choose what gets written to a file |
| Grade whether retrieved passages answer a question | Approve its own changes |

Every citation is checked against what was actually retrieved before an answer is shown.
An id the model produces that was not retrieved is stripped out and reported separately,
so an invented reference can never appear to a reader as a real one.

## What it refuses

It explains vulnerabilities and fixes them. It does not write working exploit code, and it
says so rather than quietly producing something weaker. Explaining that a header leaks to
the wrong host and that 2.31.0 fixes it is help. Handing over a script that harvests those
headers is not, and the distinction holds even when the request is framed as research.

Questions outside software security get a plain refusal rather than a confident answer in a
domain the tool knows nothing about.

## Human approval is not advisory

No file is written and no pull request is opened without a person seeing the exact diff and
approving it. This is enforced in the graph, not in the prompt: the run stops, its state is
written to SQLite, and it does not resume until a decision arrives. A rejection raises. An
edit writes only the subset that was ticked. The triage agent is handed only the read-only
tools, so it cannot write even if it decides it wants to.

## Data sources and their licences

| Source | What it gives | Licence |
| --- | --- | --- |
| [OSV](https://osv.dev) | Advisories and affected version ranges | CC-BY-4.0 |
| [NVD](https://nvd.nist.gov) | CVSS scores and CWE categories | US government work, public domain |
| [FIRST EPSS](https://www.first.org/epss/) | Exploit probability | Free for any use with attribution |
| [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) | Known exploited list | US government work, public domain |

Every advisory shown links back to osv.dev, so a reader can check the original rather than
taking this tool's word for it.

## What is logged, and for how long

`data/llm_calls.jsonl` records the time, prompt name, token counts, latency and cost of
every real model call. It does not record prompts, answers, questions or any part of a
scanned repository. Nothing is sent anywhere except the model provider.

The disk cache under `.cache/` holds model replies keyed by a hash of the request, so the
same question twice costs nothing. It is local, it is in `.gitignore`, and deleting the
directory is a complete erase.

Agent memory in `data/agent_memory.sqlite` keeps per-repository decisions, such as an
advisory the user dismissed. It exists so the tool does not nag, and it is local and
deletable for the same reason.

Nothing is retained on a server by this project. Groq's own retention is governed by their
terms, which is a reason not to send anything into a prompt that should not leave the
machine, and a reason the guardrails strip anything shaped like a credential before it can
reach one.

## Prompt injection

Advisory text and repository files are data, not instructions. They are fenced with explicit
markers before entering a prompt, and checked for override attempts first. This matters
because advisory text is written by third parties and a repository under scan may be hostile
by design. `red_team/` holds 64 attacks across the OWASP Top 10 for LLM Applications
categories, and `docs/red_team_report.md` reports what was blocked and, more usefully, what
was not.

## EU AI Act

This is not a high-risk system under Annex III. It does not touch employment, credit,
education, law enforcement, migration or essential services, and it makes no decision about
a person. It sits in the limited-risk tier, where the obligation is transparency: users must
know they are interacting with an AI system and what it can and cannot do. That is met by
the disclaimer on the interface, by this document, and by the tool refusing rather than
guessing when it does not know.

If it were ever embedded in something that gated a deployment or a release automatically,
the human approval step would be the control that keeps a person accountable for the
decision, and removing it would change the analysis.

## Known weaknesses

- The scope is 300 packages, so coverage is partial by construction.
- The generated eval questions quote their advisory ids, which flatters keyword search.
  `docs/eval_report.md` says so where the numbers are.
- The `ast` usage check sees static imports and calls. Code reached by `importlib`,
  `getattr` or a plugin system will read as unused when it is not.
- The red team numbers describe 64 attacks that were tried. They are not a guarantee about
  attacks nobody has thought of yet.
