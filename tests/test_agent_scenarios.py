from pathlib import Path

from copilot.evals.agent_scenarios import AgentScenario, read_scenarios, write_scenarios

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_there_are_ten_scenarios():
    assert len(read_scenarios()) == 10


def test_every_scenario_id_is_unique():
    scenarios = read_scenarios()
    assert len({scenario.scenario_id for scenario in scenarios}) == len(scenarios)


def test_every_scenario_says_what_it_expects():
    for scenario in read_scenarios():
        assert scenario.expectation.strip(), scenario.scenario_id
        assert scenario.name.strip(), scenario.scenario_id


def test_every_repository_a_scenario_names_exists():
    for scenario in read_scenarios():
        assert (REPO_ROOT / scenario.repository).is_dir(), scenario.repository


def test_no_scenario_expects_the_agent_to_write_anything():
    assert all(scenario.expect_no_write for scenario in read_scenarios())


def test_the_three_shapes_the_plan_asked_for_are_present():
    by_id = {scenario.scenario_id: scenario for scenario in read_scenarios()}
    assert by_id["unused-ranks-low"].must_rank_low == ["certifi", "idna"]
    assert by_id["upgrade-breaks-tests"].must_not_propose == ["breaks-tests"]
    assert by_id["no-manifest"].expect_no_findings is True


def test_scenarios_round_trip_through_disk(tmp_path):
    scenarios = read_scenarios()
    path = tmp_path / "agent_scenarios.jsonl"
    assert write_scenarios(scenarios, path) == len(scenarios)
    assert [s.scenario_id for s in read_scenarios(path)] == [s.scenario_id for s in scenarios]


def test_a_scenario_needs_an_id_a_name_and_a_repository():
    scenario = AgentScenario(
        scenario_id="x", name="n", repository="demo_vulnerable_app", expectation="e"
    )
    assert scenario.expect_no_write is True
    assert scenario.must_rank_low == []
