from copilot.evals.ragas_scores import AnsweredQuestion, RagasScores, build_dataset, ragas_section

ANSWERED = [
    AnsweredQuestion(
        question="Which version of requests fixes CVE-2023-32681?",
        answer="2.31.0",
        contexts=["Advisory GHSA-a for package requests: fixed in 2.31.0"],
        reference="2.31.0",
    )
]


def test_a_dataset_carries_the_question_answer_and_passages():
    dataset = build_dataset(ANSWERED)
    sample = dataset.samples[0]
    assert sample.user_input.startswith("Which version")
    assert sample.response == "2.31.0"
    assert sample.retrieved_contexts[0].startswith("Advisory GHSA-a")
    assert sample.reference == "2.31.0"


def test_a_question_with_no_passages_still_makes_a_valid_sample():
    empty = [AnsweredQuestion(question="q", answer="a", contexts=[], reference="r")]
    assert build_dataset(empty).samples[0].retrieved_contexts == ["no passage was retrieved"]


def test_the_section_lists_every_metric():
    result = RagasScores(
        questions=30,
        scores={"faithfulness": 0.91, "answer_relevancy": 0.88},
        seconds=120.0,
    )
    section = ragas_section(result)
    assert "| faithfulness | 0.910 |" in section
    assert "| answer_relevancy | 0.880 |" in section
    assert "over 30 questions" in section


def test_a_failed_run_says_so_instead_of_showing_nothing():
    section = ragas_section(RagasScores(questions=30, failed="RateLimitError: capped"))
    assert "did not finish" in section
    assert "RateLimitError" in section
    assert "| faithfulness |" not in section


def test_the_two_judges_are_compared_when_both_have_a_number():
    result = RagasScores(questions=30, scores={"faithfulness": 0.80})
    section = ragas_section(result, own_faithfulness=0.95)
    assert "0.950" in section
    assert "0.800" in section
    assert "neither is the truth" in section


def test_no_comparison_is_drawn_when_only_one_judge_ran():
    section = ragas_section(RagasScores(questions=30, scores={"faithfulness": 0.80}))
    assert "neither is the truth" not in section


def test_the_section_explains_why_a_second_opinion_is_worth_having():
    assert "written by someone else" in ragas_section(RagasScores())
