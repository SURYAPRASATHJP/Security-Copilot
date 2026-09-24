# Demo vulnerable app

A small Flask service pinned to old dependency versions on purpose, used as a fixture for
the copilot's scan, triage and fix flow. Do not deploy it.

Four of the eight pins are imported by `app.py` and four arrive only as transitive
dependencies, which is what makes it a useful test of whether the code really reaches a
vulnerable package.

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv -r requirements.txt pytest
.venv/bin/pytest tests
```
