import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from copilot.agents.mcp_tool_server import server

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "scan_repository_for_packages",
    "look_up_vulnerabilities",
    "check_if_code_uses_the_package",
    "find_the_lowest_safe_version",
    "run_the_project_tests",
    "update_the_requirements_file",
    "open_a_pull_request",
}
WRITE_TOOLS = {"update_the_requirements_file", "open_a_pull_request"}


def over_stdio(work):
    """Run a coroutine against the tool server started as a real subprocess."""

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "copilot.agents.mcp_tool_server"],
            env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            cwd=str(REPO_ROOT),
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await work(session)

    return asyncio.run(run())


def test_the_server_offers_every_tool():
    async def work(session):
        return await session.list_tools()

    listed = over_stdio(work)
    assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS


def test_every_tool_describes_itself_for_the_model():
    async def work(session):
        return await session.list_tools()

    for tool in over_stdio(work).tools:
        assert tool.description, f"{tool.name} has no description"
        first_word = tool.description.split(".")[0]
        assert first_word in ("Read only", "Writes"), tool.name


def test_a_read_tool_can_be_called_over_the_protocol():
    async def work(session):
        return await session.call_tool(
            "scan_repository_for_packages", {"source": "demo_vulnerable_app"}
        )

    result = over_stdio(work)
    payload = json.loads(result.content[0].text)
    assert payload["manifests"] == ["requirements.txt"]
    assert len(payload["packages"]) == 8


def test_the_write_tools_say_so_in_their_description():
    async def work(session):
        return await session.list_tools()

    by_name = {tool.name: tool for tool in over_stdio(work).tools}
    for name in WRITE_TOOLS:
        assert by_name[name].description.startswith("Writes.")
        assert "approval" in by_name[name].description
    for name in EXPECTED_TOOLS - WRITE_TOOLS:
        assert by_name[name].description.startswith("Read only.")


def test_the_server_is_registered_under_one_name():
    assert server.name == "security-copilot"
