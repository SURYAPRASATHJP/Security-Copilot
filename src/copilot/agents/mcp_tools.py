import sys
from collections.abc import Sequence
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

SERVER_NAME = "security-copilot"
REPO_ROOT = Path(__file__).resolve().parents[3]

READ_ONLY_TOOLS = (
    "scan_repository_for_packages",
    "look_up_vulnerabilities",
    "check_if_code_uses_the_package",
    "find_the_lowest_safe_version",
    "run_the_project_tests",
)
WRITE_TOOLS = ("update_the_requirements_file", "open_a_pull_request")


def server_configuration() -> dict:
    return {
        SERVER_NAME: {
            "command": sys.executable,
            "args": ["-m", "copilot.agents.mcp_tool_server"],
            "cwd": str(REPO_ROOT),
            "transport": "stdio",
        }
    }


async def load_tools() -> list:
    """Fetch the tools from the MCP server rather than importing the functions directly."""
    client = MultiServerMCPClient(server_configuration())
    return await client.get_tools()


def only(tools: Sequence, names: Sequence[str]) -> list:
    wanted = set(names)
    return [tool for tool in tools if tool.name in wanted]


def read_only(tools: Sequence) -> list:
    """Return just the tools that cannot change anything."""
    return only(tools, READ_ONLY_TOOLS)
