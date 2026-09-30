import json
from pathlib import Path

from pydantic import BaseModel, Field

# The scenarios are written by hand rather than generated, so they live with the code.
SCENARIOS_PATH = Path(__file__).parent / "agent_scenarios.jsonl"


class AgentScenario(BaseModel):
    scenario_id: str
    name: str
    repository: str
    expectation: str
    must_rank_low: list[str] = Field(default_factory=list)
    must_rank_high: list[str] = Field(default_factory=list)
    must_not_propose: list[str] = Field(default_factory=list)
    expect_no_findings: bool = False
    expect_refusal: bool = False
    expect_no_write: bool = True


def read_scenarios(path: Path | None = None) -> list[AgentScenario]:
    with (path or SCENARIOS_PATH).open(encoding="utf-8") as handle:
        return [AgentScenario.model_validate_json(line) for line in handle if line.strip()]


def write_scenarios(scenarios: list[AgentScenario], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for scenario in scenarios:
            handle.write(json.dumps(scenario.model_dump(), sort_keys=True) + "\n")
    return len(scenarios)
