# Using these tools from your own editor

The seven tools are served over MCP, so anything that speaks the protocol can use them:
Cursor, Zed, Continue, any MCP-capable desktop assistant, or your own client. Nothing about
them is specific to this project's agent.

## The config

Point your client at the server with one entry. Replace the path with wherever you cloned
this repository.

```json
{
  "mcpServers": {
    "security-copilot": {
      "command": "uv",
      "args": ["run", "python", "-m", "copilot.agents.mcp_tool_server"],
      "cwd": "/path/to/security-copilot"
    }
  }
}
```

Run `make data` and `make index` once before using it. The tools read the advisory corpus
from `data/`, and the two that search also need the index.

No key is needed for any of the seven tools. The Groq key is only used by the answering
and agent features in this repository, not by the tools themselves.

## What you get

| Tool | Changes anything? | What it does |
| --- | --- | --- |
| `scan_repository_for_packages` | no | Lists every package a repository declares |
| `look_up_vulnerabilities` | no | Finds known vulnerabilities, worst first |
| `check_if_code_uses_the_package` | no | Decides whether the code really reaches a package |
| `find_the_lowest_safe_version` | no | The lowest version on PyPI that fixes everything |
| `run_the_project_tests` | no | Installs an upgrade in a throwaway environment and runs the tests |
| `update_the_requirements_file` | yes | Repins packages, on a new branch only |
| `open_a_pull_request` | yes | Opens a pull request from a fix branch |

The two write tools refuse to touch anything other than a `requirements*.txt`, and refuse
to write to `main`, `master`, `trunk` or `develop`. Your client should still ask you before
calling them.

## Why the agent goes through this server too

The agent in `src/copilot/agents/` loads these tools over MCP rather than importing the
Python functions. That costs a subprocess and a little latency, and buys one thing worth
more: there is exactly one definition of what a tool does and what it refuses to do. A
guard added here applies to the agent and to your editor at the same time, and the tool
descriptions the model reads are the same ones you read above.
