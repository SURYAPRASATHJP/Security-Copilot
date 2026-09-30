# Agent scenario fixtures

Small repositories that each exercise one thing the agent has to get right. They are
referenced by `src/copilot/evals/agent_scenarios.jsonl` and are not meant to be run.

| Folder | What it tests |
| --- | --- |
| `no_manifest/` | The agent says it found no manifest rather than inventing packages |
| `already_current/` | A repository with nothing to fix produces no findings |
| `breaks_on_upgrade/` | A test that only passes on the old pin, so the upgrade must be reported as failing |
| `unpinned/` | Packages with no version, which the check has to flag rather than assume |
| `no_fix_available/` | A pin whose advisories have no published fix |
