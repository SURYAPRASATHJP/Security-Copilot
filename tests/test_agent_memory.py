from copilot.agents.agent_memory import (
    BROKE_TESTS,
    DISMISSED,
    RepositoryMemory,
    connect,
    dismiss_advisory,
    filter_findings,
    forget,
    recall,
    record_broken_upgrade,
    remember,
    rows_for,
    short_term_checkpointer,
)

DEMO = "demo_vulnerable_app"


def memory_db(tmp_path):
    return connect(tmp_path / "agent_memory.sqlite")


def test_a_fresh_repository_remembers_nothing(tmp_path):
    memory = recall(memory_db(tmp_path), DEMO)
    assert memory.dismissed_advisories == []
    assert memory.upgrades_that_broke_tests == {}
    assert memory.as_prompt_note() == ""


def test_a_dismissed_advisory_is_remembered(tmp_path):
    connection = memory_db(tmp_path)
    dismiss_advisory(connection, DEMO, "GHSA-j8r2")
    memory = recall(connection, DEMO)
    assert memory.should_skip_advisory("GHSA-j8r2") is True
    assert memory.should_skip_advisory("GHSA-other") is False


def test_an_upgrade_that_broke_the_tests_is_remembered(tmp_path):
    connection = memory_db(tmp_path)
    record_broken_upgrade(connection, DEMO, "requests", "2.33.0")
    memory = recall(connection, DEMO)
    assert memory.should_avoid_upgrade("requests", "2.33.0") is True
    assert memory.should_avoid_upgrade("requests", "2.32.0") is False


def test_memory_is_kept_separately_per_repository(tmp_path):
    connection = memory_db(tmp_path)
    dismiss_advisory(connection, DEMO, "GHSA-j8r2")
    assert recall(connection, "another_repo").dismissed_advisories == []


def test_remembering_the_same_thing_twice_does_not_duplicate_it(tmp_path):
    connection = memory_db(tmp_path)
    dismiss_advisory(connection, DEMO, "GHSA-j8r2")
    dismiss_advisory(connection, DEMO, "GHSA-j8r2")
    assert len(rows_for(connection, DEMO)) == 1


def test_something_remembered_can_be_forgotten(tmp_path):
    connection = memory_db(tmp_path)
    dismiss_advisory(connection, DEMO, "GHSA-j8r2")
    forget(connection, DEMO, DISMISSED, "GHSA-j8r2")
    assert recall(connection, DEMO).dismissed_advisories == []


def test_the_prompt_note_names_both_kinds_of_memory(tmp_path):
    connection = memory_db(tmp_path)
    dismiss_advisory(connection, DEMO, "GHSA-j8r2")
    record_broken_upgrade(connection, DEMO, "requests", "2.33.0")
    note = recall(connection, DEMO).as_prompt_note()
    assert "already dismissed" in note
    assert "GHSA-j8r2" in note
    assert "requests to 2.33.0 broke the tests" in note


def test_a_second_scan_skips_a_dismissed_finding():
    memory = RepositoryMemory(dismissed_advisories=["GHSA-j8r2"])
    findings = [{"advisory_id": "GHSA-j8r2"}, {"advisory_id": "GHSA-keep"}]
    assert filter_findings(findings, memory) == [{"advisory_id": "GHSA-keep"}]


def test_filtering_leaves_everything_when_nothing_was_dismissed():
    findings = [{"advisory_id": "GHSA-a"}, {"advisory_id": "GHSA-b"}]
    assert filter_findings(findings, RepositoryMemory()) == findings


def test_an_unknown_kind_of_memory_is_ignored_rather_than_crashing(tmp_path):
    connection = memory_db(tmp_path)
    remember(connection, DEMO, "something-new", "subject")
    memory = recall(connection, DEMO)
    assert memory.dismissed_advisories == []
    assert len(rows_for(connection, DEMO)) == 1


def test_the_broken_upgrade_row_records_the_version_as_its_detail(tmp_path):
    connection = memory_db(tmp_path)
    record_broken_upgrade(connection, DEMO, "requests", "2.33.0")
    row = rows_for(connection, DEMO)[0]
    assert row.kind == BROKE_TESTS
    assert row.subject == "requests"
    assert row.detail == "2.33.0"


def test_the_short_term_checkpointer_opens_on_disk(tmp_path):
    saver = short_term_checkpointer(tmp_path / "checkpoints.sqlite")
    assert saver is not None
    assert (tmp_path / "checkpoints.sqlite").exists()
