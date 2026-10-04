import pytest

from copilot.evals import report as eval_report


@pytest.fixture
def sections(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_report, "sections_dir", lambda: tmp_path / "sections")
    return tmp_path


def test_a_section_is_written_and_read_back(sections):
    eval_report.write_section(eval_report.RETRIEVAL, "## Retrieval\n\nsome numbers")
    assert "some numbers" in eval_report.read_section(eval_report.RETRIEVAL)


def test_a_missing_section_reads_as_empty(sections):
    assert eval_report.read_section(eval_report.AGENTS) == ""


def test_re_running_an_eval_replaces_its_section_rather_than_adding_one(sections):
    eval_report.write_section(eval_report.ANSWERS, "## Answers\n\nold numbers")
    eval_report.write_section(eval_report.ANSWERS, "## Answers\n\nnew numbers")
    body = eval_report.read_section(eval_report.ANSWERS)
    assert "new numbers" in body
    assert "old numbers" not in body
    assert body.count("## Answers") == 1


def test_sections_appear_in_a_fixed_order_whatever_order_they_were_written(sections, tmp_path):
    eval_report.write_section(eval_report.COST, "## Cost and latency\n\nc")
    eval_report.write_section(eval_report.AGENTS, "## Agents\n\na")
    eval_report.write_section(eval_report.RETRIEVAL, "## Retrieval\n\nr")

    path = eval_report.assemble(tmp_path / "eval_report.md")
    text = path.read_text()
    assert text.index("## Retrieval") < text.index("## Agents") < text.index("## Cost")


def test_the_report_only_contains_the_sections_that_exist(sections, tmp_path):
    eval_report.write_section(eval_report.RETRIEVAL, "## Retrieval\n\nr")
    text = eval_report.assemble(tmp_path / "eval_report.md").read_text()
    assert "## Retrieval" in text
    assert "## Agents" not in text


def test_the_report_always_carries_its_header(sections, tmp_path):
    text = eval_report.assemble(tmp_path / "eval_report.md").read_text()
    assert text.startswith("# Evaluation report")


def test_each_heading_appears_exactly_once_after_several_runs(sections, tmp_path):
    for _ in range(3):
        eval_report.write_section(eval_report.ANSWERS, "## Answers\n\nnumbers")
        eval_report.write_section(eval_report.COST, "## Cost and latency\n\nnumbers")
    text = eval_report.assemble(tmp_path / "eval_report.md").read_text()
    assert text.count("## Answers") == 1
    assert text.count("## Cost and latency") == 1


def test_sections_present_lists_only_what_was_written(sections):
    eval_report.write_section(eval_report.AGENTS, "## Agents\n\na")
    assert eval_report.sections_present() == [eval_report.AGENTS]
